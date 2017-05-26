#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
from epics.pv import fmt_time
from ophyd import PositionerBase
from ophyd.utils import DisconnectedError
from ophyd.utils.epics_pvs import (raise_if_disconnected, AlarmSeverity)
from .signal import (EpicsSignal, EpicsSignalRO)
from .device import Device
from .component import (FormattedComponent, Component)

logger = logging.getLogger(__name__)


class OMMotor(Device, PositionerBase):
    """
    Offset Mirror Motor object used in the offset mirror systems. Mostly taken
    from ophyd.epics_motor.
    """
    # position
    user_readback = Component(EpicsSignalRO, ':RBV')
    user_setpoint = Component(EpicsSignal, ':VAL', limits=True)

    # configuration
    velocity = Component(EpicsSignal, ':VELO')
    acceleration = Component(EpicsSignal, ':ACCL')

    # motor status
    motor_is_moving = Component(EpicsSignalRO, ':MOVN')
    motor_done_move = Component(EpicsSignalRO, ':DMOV')
    high_limit_switch = Component(EpicsSignal, ':HLS')
    low_limit_switch = Component(EpicsSignal, ':LLS')

    # status
    interlock = Component(EpicsSignalRO, ':INTERLOCK')
    enabled = Component(EpicsSignalRO, ':ENABLED')

    def __init__(self, prefix, *, read_attrs=None, configuration_attrs=None,
                 name=None, parent=None, **kwargs):
        if read_attrs is None:
            read_attrs = ['user_readback', 'user_setpoint']

        if configuration_attrs is None:
            configuration_attrs = ['velocity', 'acceleration', 'interlock',
                                   'enabled', 'user_offset', 'user_offset_dir']

        super().__init__(prefix, read_attrs=read_attrs,
                         configuration_attrs=configuration_attrs,
                         name=name, parent=parent, **kwargs)
        
        # Make the default alias for the user_readback the name of the
        # motor itself.
        self.user_readback.name = self.name

        self.motor_done_move.subscribe(self._move_changed)
        self.user_readback.subscribe(self._pos_changed)

    @property
    @raise_if_disconnected
    def precision(self):
        """The precision of the readback PV, as reported by EPICS"""
        return self.user_readback.precision

    @property
    @raise_if_disconnected
    def limits(self):
        return self.user_setpoint.limits

    @property
    @raise_if_disconnected
    def moving(self):
        """Whether or not the motor is moving
        Returns
        -------
        moving : bool
        """
        return bool(self.motor_is_moving.get(use_monitor=False))

    @raise_if_disconnected
    def move(self, position, wait=True, **kwargs):
        """Move to a specified position, optionally waiting for motion to
        complete.
        Parameters
        ----------
        position
            Position to move to
        moved_cb : callable
            Call this callback when movement has finished. This callback must
            accept one keyword argument: 'obj' which will be set to this
            positioner instance.
        timeout : float, optional
            Maximum time to wait for the motion. If None, the default timeout
            for this positioner is used.
        Returns
        -------
        status : MoveStatus
        Raises
        ------
        TimeoutError
            When motion takes longer than `timeout`
        ValueError
            On invalid positions
        RuntimeError
            If motion fails other than timing out
        """
        self._started_moving = False

        status = super().move(position, **kwargs)
        self.user_setpoint.put(position, wait=False)

        try:
            if wait:
                status_wait(status)
        except KeyboardInterrupt:
            self.stop()
            raise

        return status

    @property
    @raise_if_disconnected
    def position(self):
        """The current position of the motor in its engineering units
        Returns
        -------
        position : float
        """
        return self._position

    @raise_if_disconnected
    def set_current_position(self, pos):
        """Configure the motor user position to the given value
        Parameters
        ----------
        pos
           Position to set.
        """
        self.user_setpoint.put(pos, wait=True)

    def check_value(self, pos):
        """Check that the position is within the soft limits"""
        self.user_setpoint.check_value(pos)

    def _pos_changed(self, timestamp=None, value=None, **kwargs):
        """Callback from EPICS, indicating a change in position"""
        self._set_position(value)

    def _move_changed(self, timestamp=None, value=None, sub_type=None,
                      **kwargs):
        """Callback from EPICS, indicating that movement status has changed"""
        was_moving = self._moving
        self._moving = (value != 1)

        started = False
        if not self._started_moving:
            started = self._started_moving = (not was_moving and self._moving)

        logger.debug('[ts=%s] %s moving: %s (value=%s)', fmt_time(timestamp),
                     self, self._moving, value)

        if started:
            self._run_subs(sub_type=self.SUB_START, timestamp=timestamp,
                           value=value, **kwargs)

        if was_moving and not self._moving:
            success = True
            # Check if we are moving towards the low limit switch
            if self.direction_of_travel.get() == 0:
                if self.low_limit_switch.get() == 1:
                    success = False
            # No, we are going to the high limit switch
            else:
                if self.high_limit_switch.get() == 1:
                    success = False

            severity = self.user_readback.alarm_severity

            if severity != AlarmSeverity.NO_ALARM:
                status = self.user_readback.alarm_status
                logger.error('Motion failed: %s is in an alarm state '
                             'status=%s severity=%s',
                             self.name, status, severity)
                success = False

            self._done_moving(success=success, timestamp=timestamp, value=value)

    @property
    def report(self):
        try:
            rep = super().report
        except DisconnectedError:
            # TODO there might be more in this that gets lost
            rep = {'position': 'disconnected'}
        rep['pv'] = self.user_readback.pvname
        return rep

class Piezo(Device, PositionerBase):
    """
    Piezo driver object used for fine pitch adjustments.
    """
    # position
    user_readback = Component(EpicsSignalRO, ':VRBV')
    user_setpoint = Component(EpicsSignal, ':VSET', limits=True)

    # configuration
    high_limit = Component(EpicsSignal, ':VMAX')
    low_limit = Component(EpicsSignal, ':VMIN')

    # status
    enable = Component(EpicsSignalRO, ':Enable')
    stop = Component(EpicsSignalRO, ':STOP')

    def __init__(self, prefix, *, read_attrs=None, configuration_attrs=None,
                 name=None, parent=None, **kwargs):
        if read_attrs is None:
            read_attrs = ['user_readback', 'user_setpoint', 'enable']

        if configuration_attrs is None:
            configuration_attrs = ['high_limit', 'low_limit', 'enable', 
                                   'user_offset', 'user_offset_dir']

        super().__init__(prefix, read_attrs=read_attrs,
                         configuration_attrs=configuration_attrs,
                         name=name, parent=parent, **kwargs)

    @property
    @raise_if_disconnected
    def precision(self):
        '''The precision of the readback PV, as reported by EPICS'''
        return self.user_readback.precision

    @property
    @raise_if_disconnected
    def limits(self):
        return self.user_setpoint.limits

    @raise_if_disconnected
    def stop(self, *, success=False):
        self.motor_stop.put(1, wait=False)
        super().stop(success=success)

    @raise_if_disconnected
    def move(self, position, wait=True, **kwargs):
        '''Move to a specified position, optionally waiting for motion to
        complete.
        Parameters
        ----------
        position
            Position to move to
        moved_cb : callable
            Call this callback when movement has finished. This callback must
            accept one keyword argument: 'obj' which will be set to this
            positioner instance.
        timeout : float, optional
            Maximum time to wait for the motion. If None, the default timeout
            for this positioner is used.
        Returns
        -------
        status : MoveStatus
        Raises
        ------
        TimeoutError
            When motion takes longer than `timeout`
        ValueError
            On invalid positions
        RuntimeError
            If motion fails other than timing out
        '''
        self._started_moving = False

        status = super().move(position, **kwargs)
        self.user_setpoint.put(position, wait=False)

        try:
            if wait:
                status_wait(status)
        except KeyboardInterrupt:
            self.stop()
            raise

        return status

    @property
    @raise_if_disconnected
    def position(self):
        '''The current position of the motor in its engineering units
        Returns
        -------
        position : float
        '''
        return self._position

    @raise_if_disconnected
    def set_current_position(self, pos):
        '''Configure the motor user position to the given value
        Parameters
        ----------
        pos
           Position to set.
        '''
        self.set_use_switch.put(1, wait=True)
        self.user_setpoint.put(pos, wait=True)
        self.set_use_switch.put(0, wait=True)

    def check_value(self, pos):
        '''Check that the position is within the soft limits'''
        if pos < self.low_limit or pos > self.high_limit:
            raise ValueError

    def _pos_changed(self, timestamp=None, value=None, **kwargs):
        '''Callback from EPICS, indicating a change in position'''
        self._set_position(value)

    @property
    def report(self):
        try:
            rep = super().report
        except DisconnectedError:
            # TODO there might be more in this that gets lost
            rep = {'position': 'disconnected'}
        rep['pv'] = self.user_readback.pvname
        return rep    

class CouplingMotor(Device):
    """
    Device that manages the coupling between gantry motors.
    """
    gdif = Component(EpicsSignalRO, ':GDIF')
    gtol = Component(EpicsSignal, ':GTOL', limits=True)
    enabled = Component(EpicsSignal, ':ENABLED')
    decouple = Component(EpicsSignal, ':DECOUPLE')

    high_limit_switch = Component(EpicsSignal, ':HLS')
    low_limit_switch = Component(EpicsSignal, ':LLS')

    fault = Component(EpicsSignalRO, ':FAULT')

    def __init__(self, prefix, *, name=None, read_attrs=None, parent=None, 
                 configuration_attrs=None, **kwargs):
        if read_attrs is None:
            read_attrs = ['pitch', 'piezo', 'gan_x_p', 'gan_x_s']
            
        if configuration_attrs is None:
            configuration_attrs = ['gdif', 'gtol', 'enabled', 'decouple', 
                                   'fault', 'high_limit_switch', 
                                   'low_limit_switch']

        super().__init__(prefix, read_attrs=read_attrs,
                         configuration_attrs=configuration_attrs,
                         name=name, parent=parent, **kwargs)
        

    

class OffsetMirror(Device):
    """
    Device that steers the beam.
    """
    # Gantry motors
    gan_x_p = FormattedComponent(OMMotor, "STEP:{self._mirror}:X:P")
    gan_x_s = FormattedComponent(OMMotor, "STEP:{self._mirror}:X:S")
    gan_y_p = FormattedComponent(OMMotor, "STEP:{self._mirror}:X:P")
    gan_y_p = FormattedComponent(OMMotor, "STEP:{self._mirror}:X:S")

    # Piezo motor
    piezo = FormattedComponent(Piezo, "PIEZO:{self._area}:{self._mirror}")
    
    # Coupling motor
    coupling = FormattedComponent(CouplingMotor, 
                                  "STEP:{self._area}:{self._section}:MOTR")
    
    # Pitch Motor
    pitch = FormattedComponent(OMMotor, "{self._prefix}")
    
    # Currently structured to pass the ioc argument down to the pitch motor
    def __init__(self, prefix, *, name=None, read_attrs=None, parent=None, 
                 configuration_attrs=None, section="", **kwargs):
        self._prefix = prefix
        self._area = prefix.split(":")[1]
        self._mirror = prefix.split(":")[2]
        self._section = section

        if read_attrs is None:
            read_attrs = ['pitch', 'piezo', 'gan_x_p', 'gan_x_s']

        if configuration_attrs is None:
            configuration_attrs = ['pitch', 'piezo', 'gan_x_p', 'gan_x_s',
                                   'gan_y_p', 'gan_y_s', 'coupling']

        super().__init__(prefix, read_attrs=read_attrs,
                         configuration_attrs=configuration_attrs,
                         name=name, parent=parent, **kwargs)