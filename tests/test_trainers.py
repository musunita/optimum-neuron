# coding=utf-8
# Copyright 2023 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and

import copy
import os
import subprocess
import time
from tempfile import TemporaryDirectory
from unittest import TestCase

from huggingface_hub import HfApi
from transformers import TrainingArguments
from transformers.testing_utils import is_staging_test

from optimum.neuron.trainers import TrainiumTrainer
from optimum.neuron.utils.cache_utils import (
    get_neuron_cache_path,
    list_files_in_neuron_cache,
    remove_ip_adress_from_path,
    set_neuron_cache_path,
)
from optimum.neuron.utils.testing_utils import is_trainium_test

from .utils import StagingTestMixin, create_dummy_dataset, create_tiny_pretrained_model


@is_trainium_test
@is_staging_test
class TrainiumTrainerTestCase(StagingTestMixin, TestCase):
    def test_train_and_eval(self):
        os.environ["CUSTOM_CACHE_REPO"] = self.CUSTOM_PRIVATE_CACHE_REPO

        # We take a batch size that does not divide the total number of samples.
        num_train_samples = 1000
        per_device_train_batch_size = 32
        dummy_train_dataset = create_dummy_dataset({"x": (1,), "labels": (1,)}, num_train_samples)

        # We take a batch size that does not divide the total number of samples.
        num_eval_samples = 100
        per_device_eval_batch_size = 16
        dummy_eval_dataset = create_dummy_dataset({"x": (1,), "labels": (1,)}, num_eval_samples)

        model = create_tiny_pretrained_model(random_num_linears=True)
        clone = copy.deepcopy(model)

        with TemporaryDirectory() as tmpdirname:
            set_neuron_cache_path(tmpdirname)

            files_in_repo = HfApi().list_repo_files(repo_id=self.CUSTOM_PRIVATE_CACHE_REPO)
            files_in_repo = [f for f in files_in_repo if not f.startswith(".")]
            files_in_cache = list_files_in_neuron_cache(get_neuron_cache_path(), only_relevant_files=True)
            self.assertListEqual(files_in_repo, [], "Repo should be empty.")
            self.assertListEqual(files_in_cache, [], "Cache should be empty.")

            args = TrainingArguments(
                tmpdirname,
                do_train=True,
                do_eval=True,
                bf16=True,
                per_device_train_batch_size=per_device_train_batch_size,
                per_device_eval_batch_size=per_device_eval_batch_size,
                save_steps=10,
                num_train_epochs=2,
            )
            trainer = TrainiumTrainer(
                model,
                args,
                train_dataset=dummy_train_dataset,
                eval_dataset=dummy_eval_dataset,
            )
            start = time.time()
            trainer.train()
            end = time.time()
            first_training_duration = end - start

            files_in_repo = HfApi().list_repo_files(repo_id=self.CUSTOM_PRIVATE_CACHE_REPO)
            files_in_repo = [f for f in files_in_repo if not f.startswith(".")]
            files_in_cache = list_files_in_neuron_cache(get_neuron_cache_path(), only_relevant_files=True)
            self.assertNotEqual(files_in_repo, [], "Repo should not be empty after first training.")
            self.assertNotEqual(files_in_cache, [], "Cache should not be empty after first training.")

        with TemporaryDirectory() as tmpdirname:
            set_neuron_cache_path(tmpdirname)

            new_files_in_repo = HfApi().list_repo_files(repo_id=self.CUSTOM_PRIVATE_CACHE_REPO)
            new_files_in_repo = [f for f in new_files_in_repo if not f.startswith(".")]
            new_files_in_cache = list_files_in_neuron_cache(get_neuron_cache_path(), only_relevant_files=True)
            self.assertNotEqual(new_files_in_repo, [], "Repo should not be empty.")
            self.assertListEqual(new_files_in_cache, [], "Cache should be empty.")

            args = TrainingArguments(
                tmpdirname,
                do_train=True,
                do_eval=True,
                bf16=True,
                per_device_train_batch_size=per_device_train_batch_size,
                per_device_eval_batch_size=per_device_eval_batch_size,
                save_steps=10,
                num_train_epochs=2,
            )
            trainer = TrainiumTrainer(
                clone,
                args,
                train_dataset=dummy_train_dataset,
                eval_dataset=dummy_eval_dataset,
            )
            start = time.time()
            trainer.train()
            end = time.time()
            second_training_duration = end - start

            last_files_in_repo = HfApi().list_repo_files(repo_id=self.CUSTOM_PRIVATE_CACHE_REPO)
            last_files_in_repo = [f for f in last_files_in_repo if not f.startswith(".")]
            last_files_in_cache = list_files_in_neuron_cache(get_neuron_cache_path(), only_relevant_files=True)
            last_files_in_cache = [remove_ip_adress_from_path(p) for p in last_files_in_cache]
            self.assertListEqual(
                files_in_repo, last_files_in_repo, "No file should have been added to the Hub after first training."
            )
            self.assertListEqual(
                files_in_cache,
                last_files_in_cache,
                "No file should have been added to the cache after first training.",
            )

            self.assertTrue(
                second_training_duration < first_training_duration,
                "Second training should be faster because cached graphs can be used.",
            )

    def train_and_eval_multiple_workers(self):
        os.environ["CUSTOM_CACHE_REPO"] = self.CUSTOM_PRIVATE_CACHE_REPO

        with TemporaryDirectory() as tmpdirname:
            set_neuron_cache_path(tmpdirname)

            files_in_repo = HfApi().list_repo_files(repo_id=self.CUSTOM_PRIVATE_CACHE_REPO)
            files_in_repo = [f for f in files_in_repo if not f.startswith(".")]
            files_in_cache = list_files_in_neuron_cache(get_neuron_cache_path(), only_relevant_files=True)
            self.assertListEqual(files_in_repo, [], "Repo should be empty.")
            self.assertListEqual(files_in_cache, [], "Cache should be empty.")

            cmd = [
                "torchrun",
                "--nproc_per_node=2",
                "examples/text-classification/run_glue.py",
                "--model_name_or_path hf-internal-testing/tiny-random-bert",
                "--task_name=sst2",
                "--per_device_train_batch_size= 8",
                "--per_device_eval_batch_size=8",
                f"--output_dir={tmpdirname}",
                "--save_strategy=steps",
                "--save_steps=10",
                "--max_steps=100" "--do_train",
                "--do_eval",
            ]

            start = time.time()
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            end = time.time()
            first_training_duration = end - start

            _, stderr = proc.communicate()
            stderr = stderr.decode("utf-8")
            if stderr:
                print(stderr)

            self.assertEqual(proc.returncode, 0, "The first torchrun training command failed.")

            files_in_repo = HfApi().list_repo_files(repo_id=self.CUSTOM_PRIVATE_CACHE_REPO)
            files_in_repo = [f for f in files_in_repo if not f.startswith(".")]
            files_in_cache = list_files_in_neuron_cache(get_neuron_cache_path(), only_relevant_files=True)
            self.assertNotEqual(files_in_repo, [], "Repo should not be empty after first training.")
            self.assertNotEqual(files_in_cache, [], "Cache should not be empty after first training.")

        with TemporaryDirectory() as tmpdirname:
            set_neuron_cache_path(tmpdirname)

            new_files_in_repo = HfApi().list_repo_files(repo_id=self.CUSTOM_PRIVATE_CACHE_REPO)
            new_files_in_repo = [f for f in new_files_in_repo if not f.startswith(".")]
            new_files_in_cache = list_files_in_neuron_cache(get_neuron_cache_path(), only_relevant_files=True)
            self.assertNotEqual(new_files_in_repo, [], "Repo should not be empty.")
            self.assertListEqual(new_files_in_cache, [], "Cache should be empty.")

            cmd = [
                "torchrun",
                "--nproc_per_node=2",
                "examples/text-classification/run_glue.py",
                "--model_name_or_path hf-internal-testing/tiny-random-bert",
                "--task_name=sst2",
                "--per_device_train_batch_size= 8",
                "--per_device_eval_batch_size=8",
                f"--output_dir={tmpdirname}",
                "--save_strategy=steps",
                "--save_steps=10",
                "--max_steps=100" "--do_train",
                "--do_eval",
            ]

            start = time.time()
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            end = time.time()
            second_training_duration = end - start

            _, stderr = proc.communicate()
            stderr = stderr.decode("utf-8")
            if stderr:
                print(stderr)

            self.assertEqual(proc.returncode, 0, "The second torchrun training command failed.")

            last_files_in_repo = HfApi().list_repo_files(repo_id=self.CUSTOM_PRIVATE_CACHE_REPO)
            last_files_in_repo = [f for f in last_files_in_repo if not f.startswith(".")]
            last_files_in_cache = list_files_in_neuron_cache(get_neuron_cache_path(), only_relevant_files=True)
            last_files_in_cache = [remove_ip_adress_from_path(p) for p in last_files_in_cache]
            self.assertListEqual(
                files_in_repo, last_files_in_repo, "No file should have been added to the Hub after first training."
            )
            self.assertListEqual(
                files_in_cache,
                last_files_in_cache,
                "No file should have been added to the cache after first training.",
            )

            self.assertTrue(
                second_training_duration < first_training_duration,
                "Second training should be faster because cached graphs can be used.",
            )
