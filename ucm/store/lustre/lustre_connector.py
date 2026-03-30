# -*- coding: utf-8 -*-
#
# MIT License
#
# Copyright (c) 2025 Huawei Technologies Co., Ltd. All rights reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
"""
Lustre Store Connector for UCM

This module provides a Python connector for the Lustre parallel filesystem store.
It wraps C++ LustreStore implementation via pipeline and provides UcmKVStoreBaseV1 interface.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import torch

from ucm.logger import init_logger
from ucm.store.pipeline.connector import UcmPipelineStore
from ucm.store.ucmstore_v1 import Task, UcmKVStoreBaseV1

logger = init_logger(__name__)


@dataclass
class UcmLustreTask(Task):
    """Task handle for Lustre store operations."""
    task_id: int


class UcmLustreStore(UcmKVStoreBaseV1):
    """
    Lustre Store implementation for UCM.
    
    This store is optimized for Lustre parallel filesystem with features:
    - Stripe-aware I/O for parallel access
    - OST (Object Storage Target) optimization
    - Large-scale distributed storage support
    
    Configuration options:
        storage_backends: List of Lustre mount paths
        device_id: GPU/NPU device ID (-1 for CPU only)
        tensor_size: Size of each tensor element
        shard_size: Size of each shard
        block_size: Size of each block
        io_direct: Whether to use direct I/O (default: False)
        lustre_data_trans_concurrency: Data transfer concurrency (default: 16)
        lustre_lookup_concurrency: Lookup concurrency (default: 8)
        timeout_ms: Timeout in milliseconds (default: 30000)
        data_dir_shard_bytes: Data directory shard bytes (default: 2)
        stripe_count: Lustre stripe count, 0 for default (default: 0)
        stripe_size: Lustre stripe size in bytes, 0 for default (default: 0)
    """
    
    def __init__(self, config: Dict):
        """Initialize the Lustre store with configuration.
        
        Args:
            config: Configuration dictionary containing store settings.
        
        Raises:
            RuntimeError: If store initialization fails.
        """
        super().__init__(config)
        
        # Store configuration
        self._config = config
        self._storage_backends = config.get("storage_backends", [])
        self._device_id = config.get("device_id", -1)
        self._block_size = config.get("block_size", 0)
        self._tensor_size = config.get("tensor_size", 0)
        self._shard_size = config.get("shard_size", 0)
        
        # Lustre-specific configuration
        self._stripe_count = config.get("stripe_count", 0)
        self._stripe_size = config.get("stripe_size", 0)
        self._io_direct = config.get("io_direct", False)
        
        # Concurrency settings
        self._data_trans_concurrency = config.get("lustre_data_trans_concurrency", 16)
        self._lookup_concurrency = config.get("lustre_lookup_concurrency", 8)
        self._timeout_ms = config.get("timeout_ms", 30000)
        
        # Load C++ store via pipeline (liblustrestore.so)
        pipeline_config = config.copy()
        pipeline_config["store_pipeline"] = "Lustre"
        self._store = UcmPipelineStore(pipeline_config)
        self._task_counter = 0
        
        logger.info(f"UcmLustreStore initialized with backends: {self._storage_backends}")
    
    def cc_store(self) -> int:
        """Return a low-level C/C++ pointer to the underlying store.
        
        Returns:
            An opaque int representing the Store* instance.
        """
        return self._store.cc_store()
    
    def lookup(self, block_ids: List[bytes]) -> List[bool]:
        """Check presence of blocks in Lustre storage.
        
        Args:
            block_ids: List of vLLM block hashes (raw bytes).
        
        Returns:
            A list of booleans indicating block presence.
        """
        return self._store.lookup(block_ids)
    
    def lookup_on_prefix(self, block_ids: List[bytes]) -> int:
        """Find the first missing block in a prefix sequence.
        
        Args:
            block_ids: List of vLLM block hashes (raw bytes), assumed in prefix order.
        
        Returns:
            Index of first missing block, or -1 if all present.
        """
        return self._store.lookup_on_prefix(block_ids)
    
    def prefetch(self, block_ids: List[bytes]) -> None:
        """Asynchronously prefetch blocks into page cache.
        
        Args:
            block_ids: List of block IDs to prefetch.
        """
        self._store.prefetch(block_ids)
    
    def load(
        self,
        block_ids: List[bytes],
        shard_index: List[int],
        dst_tensor: List[List[torch.Tensor]],
    ) -> Task:
        """Load KV cache data from Lustre storage to device memory.
        
        Args:
            block_ids: List of block IDs to load.
            shard_index: Shard indices for each block.
            dst_tensor: Destination tensor buffers organized by [block][layer].
        
        Returns:
            Task handle for tracking completion.
        """
        return self._store.load(block_ids, shard_index, dst_tensor)
    
    def dump(
        self,
        block_ids: List[bytes],
        shard_index: List[int],
        src_tensor: List[List[torch.Tensor]],
    ) -> Task:
        """Dump KV cache data from device memory to Lustre storage.
        
        Args:
            block_ids: List of block IDs to dump.
            shard_index: Shard indices for each block.
            src_tensor: Source tensor buffers organized by [block][layer].
        
        Returns:
            Task handle for tracking completion.
        """
        return self._store.dump(block_ids, shard_index, src_tensor)
    
    def load_data(
        self,
        block_ids: List[bytes],
        shard_index: List[int],
        dst_addr: List[List[int]] | np.ndarray,
    ) -> Task:
        """Low-level load: copy KV data to device pointers.
        
        Args:
            block_ids: List of block IDs to load.
            shard_index: Shard indices for each block.
            dst_addr: Destination memory addresses.
        
        Returns:
            Task handle for tracking completion.
        """
        return self._store.load_data(block_ids, shard_index, dst_addr)
    
    def dump_data(
        self,
        block_ids: List[bytes],
        shard_index: List[int],
        src_addr: List[List[int]] | np.ndarray,
    ) -> Task:
        """Low-level dump: copy KV data from device pointers.
        
        Args:
            block_ids: List of block IDs to dump.
            shard_index: Shard indices for each block.
            src_addr: Source memory addresses.
        
        Returns:
            Task handle for tracking completion.
        """
        return self._store.dump_data(block_ids, shard_index, src_addr)
    
    def wait(self, task: Task) -> None:
        """Block until the given transfer task completes.
        
        Args:
            task: Task handle to wait for.
        """
        self._store.wait(task)
    
    def check(self, task: Task) -> bool:
        """Non-blocking poll for task completion.
        
        Args:
            task: Task handle to check.
        
        Returns:
            True if task is complete, False otherwise.
        """
        return self._store.check(task)
    
    def __repr__(self) -> str:
        return (
            f"UcmLustreStore("
            f"backends={self._storage_backends}, "
            f"device_id={self._device_id}, "
            f"stripe_count={self._stripe_count}, "
            f"stripe_size={self._stripe_size})"
        )
