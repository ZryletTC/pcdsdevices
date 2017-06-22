#!/usr/bin/env python
# -*- coding: utf-8 -*-
############
# Standard #
############
import time

###############
# Third Party #
###############
import numpy as np

##########
# Module #
##########
from .sim import SimDevice
from .signal import (Signal, FakeSignal)
from .component import (FormattedComponent, Component, DynamicDeviceComponent)
from ..epics import mirror


class OMMotor(mirror.OMMotor):
    # TODO: Write a proper docstring
    """
    Offset Mirror Motor object used in the offset mirror systems. Mostly taken
    from ophyd.epics_motor.
    """
    # position
    user_readback = Component(FakeSignal, value=0)
    user_setpoint = Component(FakeSignal, value=0)

    # configuration
    velocity = Component(Signal)

    # motor status
    motor_is_moving = Component(FakeSignal, value=0)
    motor_done_move = Component(FakeSignal, value=1)
    high_limit_switch = Component(FakeSignal, value=10000)
    low_limit_switch = Component(FakeSignal, value=-10000)

    # status
    interlock = Component(FakeSignal)
    enabled = Component(FakeSignal)

    motor_stop = Component(FakeSignal)

    def __init__(self, prefix, *, read_attrs=None, configuration_attrs=None,
                 name=None, parent=None, velocity=0, noise=0, settle_time=0, 
                 noise_func=None, noise_type="uni", noise_args=(), 
                 noise_kwargs={}, **kwargs):
        super().__init__(prefix, read_attrs=read_attrs,
                         configuration_attrs=configuration_attrs, name=name, 
                         parent=parent, settle_time=settle_time, **kwargs)
        self.velocity.put(velocity)
        self.noise = noise
        self.settle_time = settle_time
        self.noise_type = noise_type
        self.noise_args = noise_args
        self.noise_kwargs = noise_kwargs
        self.user_setpoint.velocity = lambda : self.velocity.value

    def move(self, position, **kwargs):
        """
        Move to a specified position, optionally waiting for motion to
        complete.

        Parameters
        ----------
        position
            Position to move to

        Returns
        -------
        status : MoveStatus
        """
        self.user_setpoint.put(position)

        # Switch to moving state
        self.motor_is_moving.put(1)
        self.motor_done_move.put(0)
        status = self.user_readback.set(position)

        # # Switch to finished state and wait for status to update
        self.motor_is_moving.put(0)
        self.motor_done_move.put(1)
        time.sleep(0.1)
        return status

    @property
    def noise(self):
        return self.user_readback.noise

    @noise.setter
    def noise(self, val):
        self.user_readback.noise = bool(val)

    @property
    def settle_time(self):
        if callable(self.user_setpoint.put_sleep):
            return self.user_setpoint.put_sleep()
        return self.user_setpoint.put_sleep

    @settle_time.setter
    def settle_time(self, val):
        self.user_setpoint.put_sleep = val

    @property
    def noise_func(self):
        if callable(self.user_readback.noise_func):
            return self.user_readback.noise_func()
        return self.user_readback.noise_func

    @noise_func.setter
    def noise_func(self, val):
        self.user_readback.noise_func = val

    @property
    def noise_type(self):
        return self.user_readback.noise_type

    @noise_type.setter
    def noise_type(self, val):
        self.user_readback.noise_type = val

    @property
    def noise_args(self):
        return self.user_readback.noise_args

    @noise_args.setter
    def noise_args(self, val):
        self.user_readback.noise_args = val

    @property
    def noise_kwargs(self):
        return self.user_readback.noise_kwargs

    @noise_kwargs.setter
    def noise_kwargs(self, val):
        self.user_readback.noise_kwargs = val


class OffsetMirror(mirror.OffsetMirror, SimDevice):
    # TODO: Add all parameters to doc string
    """
    Simulation of a simple flat mirror with assorted motors.
    
    Parameters
    ----------
    name : string
        Name of motor

    x : float
        Initial position of x-motor

    z : float
        Initial position of z-motor

    alpha : float
        Initial position of alpha-motor

    noise_x : float, optional
        Multiplicative noise factor added to x-motor readback

    noise_z : float, optional
        Multiplicative noise factor added to z-motor readback

    noise_alpha : float, optional
        Multiplicative noise factor added to alpha-motor readback
    
    fake_sleep_x : float, optional
        Amount of time to wait after moving x-motor

    fake_sleep_z : float, optional
        Amount of time to wait after moving z-motor

    fake_sleep_alpha : float, optional
        Amount of time to wait after moving alpha-motor
    """
    # Gantry Motors
    gan_x_p = FormattedComponent(OMMotor, "STEP:{self._mirror}:X:P")
    gan_x_s = FormattedComponent(OMMotor, "STEP:{self._mirror}:X:S")
    gan_y_p = FormattedComponent(OMMotor, "STEP:{self._mirror}:Y:P")
    gan_y_s = FormattedComponent(OMMotor, "STEP:{self._mirror}:Y:S")
    
    # Pitch Motor
    pitch = FormattedComponent(OMMotor, "{self._prefix}")

    # Placeholder signals for non-implemented components
    piezo = Component(FakeSignal)
    coupling = Component(FakeSignal)
    motor_stop = Component(FakeSignal)

    # Simulation component
    sim_alpha = Component(FakeSignal)

    def __init__(self, prefix, *, name=None, read_attrs=None, parent=None, 
                 configuration_attrs=None, section="", x=0, y=0, z=0, alpha=0, 
                 velo_x=0, velo_y=0, velo_z=0, velo_alpha=0, noise_x=0, 
                 noise_y=0, noise_z=0, noise_alpha=0, settle_time_x=0, 
                 settle_time_y=0, settle_time_z=0, settle_time_alpha=0, 
                 noise_func=None, noise_type="uni", noise_args=(), 
                 noise_kwargs={}, **kwargs):
        if len(prefix.split(":")) < 3:
            prefix = "MIRR:TST:{0}".format(prefix)
        super().__init__(prefix, read_attrs=read_attrs,
                         configuration_attrs=configuration_attrs,
                         name=name, parent=parent, **kwargs)
        self.log_pref = "{0} (OffsetMirror) - ".format(self.name)

        # Simulation Attributes
        # Fake noise to readback and moves
        self.noise_x = noise_x
        self.noise_y = noise_y
        self.noise_z = noise_z
        self.noise_alpha = noise_alpha
        
        # Settle time for every move
        self.settle_time_x = settle_time_x
        self.settle_time_y = settle_time_y
        self.settle_time_z = settle_time_z
        self.settle_time_alpha = settle_time_alpha

        # Velocity for every move
        self.velo_x = velo_x
        self.velo_y = velo_y
        self.velo_z = velo_z
        self.velo_alpha = velo_alpha
        
        # Set initial position values
        self.gan_x_p.user_setpoint.put(x)
        self.gan_x_p.user_readback.put(x)
        self.gan_x_s.user_setpoint.put(x)
        self.gan_x_s.user_readback.put(x)
        self.gan_y_p.user_setpoint.put(y)
        self.gan_y_p.user_readback.put(y)
        self.gan_y_s.user_setpoint.put(y)
        self.gan_y_s.user_readback.put(y)
        self.sim_z.put(z)
        self.pitch.user_setpoint.put(alpha)
        self.pitch.user_readback.put(alpha)

        # Noise parameters
        self.noise_func = noise_func
        self.noise_type = noise_type
        self.noise_args = noise_args
        self.noise_kwargs = noise_kwargs

        # Simulation values
        self.sim_x._get_readback = lambda : self.gan_x_p.user_readback.value
        self.sim_y._get_readback = lambda : self.gan_y_p.user_readback.value
        self.sim_z.put(z)
        self.sim_alpha._get_readback = lambda : self.pitch.user_readback.value

    # Coupling motor isnt implemented as an example so override its properties
    @property
    def decoupled(self):
        return False

    @property
    def fault(self):
        return False

    @property
    def gdif(self):
        return 0.0
    
    @property
    def noise_x(self):
        return self.gan_x_p.noise

    @noise_x.setter
    def noise_x(self, val):
        self.gan_x_p.noise = self.gan_x_s.noise = bool(val)

    @property
    def noise_y(self):
        return self.gan_y_p.noise

    @noise_y.setter
    def noise_y(self, val):
        self.gan_y_p.noise = self.gan_y_s.noise = bool(val)

    @property
    def noise_z(self):
        return self.sim_z.noise

    @noise_z.setter
    def noise_z(self, val):
        self.sim_z.noise = bool(val)

    @property
    def noise_alpha(self):
        return self.pitch.noise

    @noise_alpha.setter
    def noise_alpha(self, val):
        self.pitch.noise = bool(val)
    
    @property
    def settle_time_x(self):
        return self.gan_x_p.settle_time

    @settle_time_x.setter
    def settle_time_x(self, val):
        self.gan_x_p.settle_time = self.gan_x_s.settle_time = val

    @property
    def settle_time_y(self):
        return self.gan_y_p.settle_time

    @settle_time_y.setter
    def settle_time_y(self, val):
        self.gan_y_p.settle_time = self.gan_y_s.settle_time = val

    @property
    def settle_time_z(self):
        return self.sim_z.put_sleep

    @noise_z.setter
    def settle_time_z(self, val):
        self.sim_z.put_sleep = val

    @property
    def settle_time_alpha(self):
        return self.pitch.settle_time

    @settle_time_alpha.setter
    def settle_time_alpha(self, val):
        self.pitch.settle_time = val

    @property
    def velocity_x(self):
        return self.gan_x_p.velocity.value

    @velocity_x.setter
    def velocity_x(self, val):
        self.gan_x_p.velocity.value = self.gan_x_s.velocity.value = val

    @property
    def velocity_y(self):
        return self.gan_y_p.velocity.value

    @velocity_y.setter
    def velocity_y(self, val):
        self.gan_y_p.velocity.value = self.gan_y_s.velocity.value = val

    @property
    def velocity_z(self):
        return self.sim_z.velocity

    @velocity_z.setter
    def velocity_z(self, val):
        self.sim_z.velocity = val

    @property
    def velocity_alpha(self):
        return self.pitch.velocity.value

    @velocity_alpha.setter
    def velocity_alpha(self, val):
        self.pitch.velocity.value = val

    @property
    def noise_func(self):
        if callable(self.pitch.noise_func):
            return self.pitch.noise_func()
        return self.pitch.noise_func

    @noise_func.setter
    def noise_func(self, val):
        self.gan_x_p.noise_func = val
        self.gan_y_p.noise_func = val
        self.sim_z.noise_func = val
        self.pitch.noise_func = val

    @property
    def noise_type(self):
        return self.pitch.noise_type

    @noise_type.setter
    def noise_type(self, val):
        self.gan_x_p.noise_type = val
        self.gan_y_p.noise_type = val
        self.sim_z.noise_type = val
        self.pitch.noise_type = val

    @property
    def noise_args(self):
        return self.pitch.noise_args

    @noise_args.setter
    def noise_args(self, val):
        self.gan_x_p.noise_args = val
        self.gan_y_p.noise_args = val
        self.sim_z.noise_args = val
        self.pitch.noise_args = val

    @property
    def noise_kwargs(self):
        return self.pitch.noise_kwargs

    @noise_kwargs.setter
    def noise_kwargs(self, val):
        self.gan_x_p.noise_kwargs = val
        self.gan_y_p.noise_kwargs = val
        self.sim_z.noise_kwargs = val
        self.pitch.noise_kwargs = val

