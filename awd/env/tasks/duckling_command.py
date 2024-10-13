import torch

import env.tasks.duckling as duckling
import env.tasks.duckling_amp as duckling_amp
import env.tasks.duckling_amp_task as duckling_amp_task
from utils import torch_utils

from isaacgym import gymapi
from isaacgym import gymtorch
from isaacgym.torch_utils import *

TAR_ACTOR_ID = 1
TAR_FACING_ACTOR_ID = 2

class DucklingCommand(duckling_amp_task.DucklingAMPTask):
    def __init__(self, cfg, sim_params, physics_engine, device_type, device_id, headless):
        super().__init__(cfg=cfg,
                         sim_params=sim_params,
                         physics_engine=physics_engine,
                         device_type=device_type,
                         device_id=device_id,
                         headless=headless)
        
        # normalization
        self.lin_vel_scale = self.cfg["env"]["learn"]["linearVelocityScale"]
        self.ang_vel_scale = self.cfg["env"]["learn"]["angularVelocityScale"]

        # reward scales
        self.rew_scales = {}
        self.rew_scales["lin_vel_xy"] = self.cfg["env"]["learn"]["linearVelocityXYRewardScale"]
        self.rew_scales["ang_vel_z"] = self.cfg["env"]["learn"]["angularVelocityZRewardScale"]
        self.rew_scales["torque"] = self.cfg["env"]["learn"]["torqueRewardScale"]

        # randomization
        self.randomization_params = self.cfg["task"]["randomization_params"]
        self.randomize = self.cfg["task"]["randomize"]

        # command ranges
        self.command_x_range = self.cfg["env"]["randomCommandVelocityRanges"]["linear_x"]
        self.command_y_range = self.cfg["env"]["randomCommandVelocityRanges"]["linear_y"]
        self.command_yaw_range = self.cfg["env"]["randomCommandVelocityRanges"]["yaw"]
        
        # for key in self.rew_scales.keys():
        #     self.rew_scales[key] *= self.dt

        self.rew_scales["torque"] *= self.dt

        # rename variables to maintain consistency with anymal env
        self.root_states = self._root_states
        self.dof_state = self._dof_state
        self.dof_pos = self._dof_pos
        self.dof_vel = self._dof_vel
        self.contact_forces = self._contact_forces
        self.torques = self.dof_force_tensor

        self.commands = torch.zeros(self.num_envs, 3, dtype=torch.float, device=self.device, requires_grad=False)
        self.commands_y = self.commands.view(self.num_envs, 3)[..., 1]
        self.commands_x = self.commands.view(self.num_envs, 3)[..., 0]
        self.commands_yaw = self.commands.view(self.num_envs, 3)[..., 2]
        self.commands_scale = torch.tensor([self.lin_vel_scale, self.lin_vel_scale, self.ang_vel_scale], requires_grad=False, device=self.commands.device)
        self.default_dof_pos = torch.zeros_like(self.dof_pos, dtype=torch.float, device=self.device, requires_grad=False)
        
        return

    def get_task_obs_size(self):
        obs_size = 0
        if (self._enable_task_obs):
            obs_size = 3
        return obs_size

    def pre_physics_step(self, actions):
        super().pre_physics_step(actions)
        return
    
    def _create_envs(self, num_envs, spacing, num_per_row):
        super()._create_envs(num_envs, spacing, num_per_row)
        return

    def _build_env(self, env_id, env_ptr, duckling_asset):
        super()._build_env(env_id, env_ptr, duckling_asset)
        return

    def _update_task(self):
        # TODO: change commands after certain steps.
        # reset_task_mask = self.progress_buf >= self._heading_change_steps
        # rest_env_ids = reset_task_mask.nonzero(as_tuple=False).flatten()
        # if len(rest_env_ids) > 0:
        #     self._reset_task(rest_env_ids)
        return

    def _reset_task(self, env_ids):
        # Randomization can happen only at reset time, since it can reset actor positions on GPU
        if self.randomize:
            self.apply_randomizations(self.randomization_params)
        
        self.commands_x[env_ids] = torch_rand_float(self.command_x_range[0], self.command_x_range[1], (len(env_ids), 1), device=self.device).squeeze()
        self.commands_y[env_ids] = torch_rand_float(self.command_y_range[0], self.command_y_range[1], (len(env_ids), 1), device=self.device).squeeze()
        self.commands_yaw[env_ids] = torch_rand_float(self.command_yaw_range[0], self.command_yaw_range[1], (len(env_ids), 1), device=self.device).squeeze()

        return

    def _compute_task_obs(self, env_ids=None):
        if (env_ids is None):
            obs = self.commands * self.commands_scale
        else:
            obs = self.commands[env_ids] * self.commands_scale
        return obs

    def _compute_reward(self, actions):
        self.rew_buf[:] = compute_task_reward(self._duckling_root_states, self.commands,  self.torques, self.rew_scales)
        return

#####################################################################
###=========================jit functions=========================###
#####################################################################

@torch.jit.script
def compute_task_observations(commands, command_scales):
    # type: (Tensor, Tensor) -> Tensor
    commands_scaled = commands * command_scales
    obs = commands_scaled
    return obs

@torch.jit.script
def compute_task_reward(
    # tensors
    root_states,
    commands,
    torques,
    # Dict
    rew_scales,
):
    # (reward, reset, feet_in air, feet_air_time, episode sums)
    # type: (Tensor, Tensor, Tensor, Dict[str, float]) -> Tensor

    # prepare quantities (TODO: return from obs ?)
    base_quat = root_states[:, 3:7]
    base_lin_vel = quat_rotate_inverse(base_quat, root_states[:, 7:10])
    base_ang_vel = quat_rotate_inverse(base_quat, root_states[:, 10:13])

    # velocity tracking reward
    lin_vel_error = torch.sum(torch.square(commands[:, :2] - base_lin_vel[:, :2]), dim=1)
    ang_vel_error = torch.square(commands[:, 2] - base_ang_vel[:, 2])
    rew_lin_vel_xy = torch.exp(-lin_vel_error/0.25) * rew_scales["lin_vel_xy"]
    rew_ang_vel_z = torch.exp(-ang_vel_error/0.25) * rew_scales["ang_vel_z"]

    # torque penalty
    rew_torque = torch.sum(torch.square(torques), dim=1) * rew_scales["torque"]

    total_reward = rew_lin_vel_xy + rew_ang_vel_z + rew_torque
    total_reward = torch.clip(total_reward, 0., None)

    #print("task reward:", total_reward)
    return total_reward