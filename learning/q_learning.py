import torch
import numpy as np
import random
from collections import deque, namedtuple

import gymnasium as gym
import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import random
from collections import deque, namedtuple
import matplotlib.pyplot as plt
import torch.nn.functional as F
import os
import copy

from learning.models import MahjongNetwork
from simulator.tiles import Tile
from simulator.util import index_to_tile, tile_to_index

device = torch.device("mps")
    

class ReplayBuffer:
    def __init__(self, action_size: int, buffer_size: int, batch_size: int, seed: int):
        self.action_size = action_size
        self.memory = deque(maxlen=buffer_size)
        self.batch_size = batch_size
        self.experience = namedtuple("Experience", field_names=["state", "action", "reward", "next_state", "done"])
        self.seed = random.seed(seed)

    def add(self, state: torch.Tensor, action: int, reward: float, next_state: torch.Tensor, done: bool):
        """Add a new experience to memory."""
        # print("SHAPE: ")
        # print(state.shape)
        self.memory.append(self.experience(state, action, reward, next_state, done))

    def sample(self) -> tuple:
        experiences = random.sample(self.memory, k=self.batch_size)
        states = torch.stack([e.state for e in experiences if e is not None]).float().to(device)
        actions = torch.tensor([e.action for e in experiences if e is not None]).long().to(device)
        rewards = torch.tensor([e.reward for e in experiences if e is not None]).float().to(device)
        next_states = torch.stack([e.next_state for e in experiences if e is not None]).float().to(device)
        dones = torch.tensor([e.done for e in experiences if e is not None]).bool().to(device)
        return (states, actions, rewards, next_states, dones)
    
    def __len__(self) -> int:
        """Return the current size of internal memory."""
        return len(self.memory)

class DQNTrainer:
    def __init__(self, model: MahjongNetwork, buffer_size: int, batch_size: int, lr: float, gamma: int, tau: int, epsilon: int, seed: int):
        self.qnetwork_local = model
        torch.save(self.qnetwork_local.state_dict(), 'network.pth')

        self.qnetwork_target = MahjongNetwork(self.qnetwork_local.input_channels, self.qnetwork_local.output_size, seed).to(device)
        self.qnetwork_target.load_state_dict(torch.load('network.pth'))
        self.qnetwork_target.eval()

        self.optimizer = optim.Adam(self.qnetwork_local.parameters(), lr=lr)
        self.gamma = gamma
        self.tau = tau
        self.epsilon = epsilon
        self.action_size = model.output_size

        self.memory = ReplayBuffer(self.action_size, buffer_size=buffer_size, batch_size=batch_size, seed=seed)

    def step(self, state: torch.Tensor, action: int, reward: float, next_state: torch.Tensor, done: bool):
        self.memory.add(state, action, reward, next_state, done)

        if len(self.memory.memory) > self.memory.batch_size:
            experiences = self.memory.sample()
            self.learn(experiences)

    def act(self, state: torch.Tensor, hand: list[Tile]):
        state = state.float().unsqueeze(0).to(device)
        self.qnetwork_local.eval()
        with torch.no_grad():
            action_values = self.qnetwork_local(state).detach().cpu().numpy()
        self.qnetwork_local.train()

        #Epsilon-greedy
        if np.random.rand() < self.epsilon:
            return tile_to_index(np.random.choice(hand))

        order = np.flip(np.argsort(action_values))

        extra_attempts = 0
        discard_tile = None
        while (discard_tile not in hand):
            action = order[0, extra_attempts]
            discard_tile = index_to_tile(action)
            extra_attempts += 1

        return action
    
    def act_meld(self, state: torch.Tensor):
        state = state.float().unsqueeze(0).to(device)
        self.qnetwork_local.eval()
        with torch.no_grad():
            action_values = self.qnetwork_local(state)
        self.qnetwork_local.train()

        return action_values
        #Epsilon-greedy
        best = np.argmax(action_values)
        weights = np.full_like(action_values, self.epsilon / (self.action_size - 1))
        weights[best] = 1 - self.epsilon
        return np.random.choice(self.action_size, p=weights)

    def learn(self, experiences):
        states, actions, rewards, next_states, dones = experiences
        # next_states = next_states.to(device)
        action_values = self.qnetwork_target(next_states).detach()
        max_action_values = action_values.max(1)[0].unsqueeze(1)

        q_targets = rewards.unsqueeze(1) + (self.gamma * max_action_values * (1 - dones.unsqueeze(1).long()))
        q_expected = self.qnetwork_local(states).gather(1, actions.unsqueeze(1))

        loss = F.mse_loss(q_expected, q_targets)
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()

        self.soft_update()
    
    def end_step(self, state: torch.Tensor, action: int, reward: float, next_state: torch.Tensor, done: bool):
        self.memory.add(state, action, reward, next_state, done)

        if len(self.memory.memory) > self.memory.batch_size:
            experiences = self.memory.sample()
            self.learn(experiences)
        
    # def end_learn(self, experiences):
    #     states, actions, rewards, next_states, dones = experiences

    #     q_targets = rewards.unsqueeze(1)
    #     q_expected = self.qnetwork_local(states).gather(1, actions.unsqueeze(1))

    #     loss = F.mse_loss(q_expected, q_targets)
    #     self.optimizer.zero_grad()
    #     loss.backward()
    #     self.optimizer.step()

    #     self.soft_update()
    
    def soft_update(self):
        for target_param, local_param in zip(self.qnetwork_target.parameters(), self.qnetwork_local.parameters()):
            target_param.data.copy_(self.tau*local_param.data + (1.0-self.tau)*target_param.data)