#!/usr/bin/env python3
# Copyright (c) Facebook, Inc. and its affiliates. All rights reserved.

import dataclasses
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Type, TypeVar, Union, cast

import numpy as np
import torch


@dataclass
class BaseDataClass:
    def _replace(self, **kwargs):
        return cast(type(self), dataclasses.replace(self, **kwargs))


@dataclass
class ValuePresence(BaseDataClass):
    value: torch.Tensor
    presence: Optional[torch.ByteTensor]


@dataclass
class IdFeatureConfig(BaseDataClass):
    """
    This describes how to map raw features to model features
    """

    feature_id: int  # integer feature ID
    id_mapping_name: str  # key to ModelPreprocessingConfig.id_mapping_config


@dataclass
class IdFeatureBase(BaseDataClass):
    """
    User should subclass this class and define each ID feature as a field w/ torch.Tensor
    as the type of the field.
    """

    @classmethod
    # TODO: This should be marked as abstractmethod but mypi doesn't like it.
    # See https://github.com/python/mypy/issues/5374
    # @abc.abstractmethod
    def get_feature_config(cls) -> Dict[str, IdFeatureConfig]:
        """
        Returns mapping from feature name, which must be a field in this dataclass, to
        feature config.
        """
        raise NotImplementedError


T = TypeVar("T", bound="SequenceFeatureBase")


@dataclass
class FloatFeatureInfo(BaseDataClass):
    name: str
    feature_id: int


@dataclass
class SequenceFeatureBase(BaseDataClass):
    id_features: Optional[IdFeatureBase]
    float_features: Optional[ValuePresence]

    @classmethod
    # TODO: This should be marked as abstractmethod but mypi doesn't like it.
    # See https://github.com/python/mypy/issues/5374
    # @abc.abstractmethod
    def get_max_length(cls) -> int:
        """
        Subclass should return the max-length of this sequence. If the raw data is
        longer, feature extractor will truncate the front. If the raw data is shorter,
        feature extractor will fill the front with zero.
        """
        raise NotImplementedError

    @classmethod
    def get_float_feature_infos(cls) -> List[FloatFeatureInfo]:
        """
        Override this if the sequence has float features associated to it.
        Float features should be stored as ID-score-list, where the ID part corresponds
        to primary entity ID of the sequence. E.g., if this is a sequence of previously
        watched videos, then the key should be video ID.
        """
        return []

    @classmethod
    def prototype(cls: Type[T]) -> T:
        float_feature_infos = cls.get_float_feature_infos()
        float_features = (
            torch.rand(1, cls.get_max_length(), len(float_feature_infos))
            if float_feature_infos
            else None
        )
        fields = dataclasses.fields(cls)
        id_features = None
        for field in fields:
            if field.name != "id_features" or not isinstance(field.type, type):
                continue
            id_feature_fields = dataclasses.fields(field.type)
            id_features = field.type(  # noqa
                **{
                    f.name: torch.randint(1, (1, cls.get_max_length()))
                    for f in id_feature_fields
                }
            )
            break

        return cls(id_features=id_features, float_features=float_features)


U = TypeVar("U", bound="SequenceFeatures")


@dataclass
class SequenceFeatures(BaseDataClass):
    """
    A stub-class for sequence features in the model. All fileds should be subclass of
    SequenceFeatureBase above.
    """

    @classmethod
    def prototype(cls: Type[U]) -> U:
        fields = dataclasses.fields(cls)
        return cls(**{f.name: f.type.prototype() for f in fields})  # type: ignore


@dataclass
class IdMapping(BaseDataClass):
    ids: List[int]


@dataclass
class ModelFeatureConfig(BaseDataClass):
    float_feature_infos: List[FloatFeatureInfo]
    id_mapping_config: Dict[str, IdMapping]
    sequence_features_type: Optional[Type[SequenceFeatures]]


@dataclass
class FeatureVector(BaseDataClass):
    float_features: ValuePresence
    # sequence_features should ideally be Mapping[str, IdListFeature]; however,
    # that doesn't work well with ONNX.
    # User is expected to dynamically define the type of id_list_features based
    # on the actual features used in the model.
    sequence_features: Optional[SequenceFeatureBase] = None
    # Experimental: sticking this here instead of putting it in float_features
    # because a lot of places derive the shape of float_features from
    # normalization parameters.
    time_since_first: Optional[torch.Tensor] = None


@dataclass
class ActorOutput(BaseDataClass):
    action: torch.Tensor
    log_prob: Optional[torch.Tensor] = None


@dataclass
class PreprocessedState(BaseDataClass):
    """
    This class makes it easier to plug modules into predictor
    """

    state: torch.Tensor


@dataclass
class PreprocessedStateAction(BaseDataClass):
    state: torch.Tensor
    action: torch.Tensor


@dataclass
class RawStateAction(BaseDataClass):
    state: FeatureVector
    action: FeatureVector


@dataclass
class CommonInput(BaseDataClass):
    """
    Base class for all inputs, both raw and preprocessed
    """

    reward: torch.Tensor
    time_diff: torch.Tensor
    step: Optional[torch.Tensor]
    not_terminal: torch.Tensor


@dataclass
class PreprocessedBaseInput(CommonInput):
    state: torch.Tensor
    next_state: torch.Tensor


@dataclass
class PreprocessedDiscreteDqnInput(PreprocessedBaseInput):
    action: torch.Tensor
    next_action: torch.Tensor
    possible_actions_mask: torch.Tensor
    possible_next_actions_mask: torch.Tensor


@dataclass
class PreprocessedParametricDqnInput(PreprocessedBaseInput):
    action: torch.Tensor
    next_action: torch.Tensor
    possible_actions: torch.Tensor
    possible_actions_mask: torch.ByteTensor
    possible_next_actions: torch.Tensor
    possible_next_actions_mask: torch.ByteTensor
    tiled_next_state: torch.Tensor


@dataclass
class PreprocessedPolicyNetworkInput(PreprocessedBaseInput):
    action: torch.Tensor
    next_action: torch.Tensor


@dataclass
class PreprocessedMemoryNetworkInput(PreprocessedBaseInput):
    action: Union[torch.Tensor, torch.Tensor]


@dataclass
class RawBaseInput(CommonInput):
    state: FeatureVector
    next_state: FeatureVector


@dataclass
class RawDiscreteDqnInput(RawBaseInput):
    action: torch.ByteTensor
    next_action: torch.ByteTensor
    possible_actions_mask: torch.ByteTensor
    possible_next_actions_mask: torch.ByteTensor

    def preprocess(self, state: torch.Tensor, next_state: torch.Tensor):
        return PreprocessedDiscreteDqnInput(
            self.reward,
            self.time_diff,
            self.step,
            self.not_terminal.float(),
            state,
            next_state,
            self.action.float(),
            self.next_action.float(),
            self.possible_actions_mask.float(),
            self.possible_next_actions_mask.float(),
        )


@dataclass
class RawParametricDqnInput(RawBaseInput):
    action: FeatureVector
    next_action: FeatureVector
    possible_actions: FeatureVector
    possible_actions_mask: torch.ByteTensor
    possible_next_actions: FeatureVector
    possible_next_actions_mask: torch.ByteTensor
    tiled_next_state: FeatureVector

    def preprocess(
        self,
        state: torch.Tensor,
        next_state: torch.Tensor,
        action: torch.Tensor,
        next_action: torch.Tensor,
        possible_actions: torch.Tensor,
        possible_next_actions: torch.Tensor,
        tiled_next_state: torch.Tensor,
    ):
        return PreprocessedParametricDqnInput(
            self.reward,
            self.time_diff,
            self.step,
            self.not_terminal,
            state,
            next_state,
            action,
            next_action,
            possible_actions,
            self.possible_actions_mask,
            possible_next_actions,
            self.possible_next_actions_mask,
            tiled_next_state,
        )


@dataclass
class RawPolicyNetworkInput(RawBaseInput):
    action: FeatureVector
    next_action: FeatureVector

    def preprocess(
        self,
        state: torch.Tensor,
        next_state: torch.Tensor,
        action: torch.Tensor,
        next_action: torch.Tensor,
    ):
        return PreprocessedPolicyNetworkInput(
            self.reward,
            self.time_diff,
            self.step,
            self.not_terminal,
            state,
            next_state,
            action,
            next_action,
        )


@dataclass
class RawMemoryNetworkInput(RawBaseInput):
    action: Union[FeatureVector, torch.ByteTensor]

    def preprocess(
        self,
        state: torch.Tensor,
        next_state: torch.Tensor,
        action: Optional[torch.Tensor] = None,
    ):
        if action is not None:
            return PreprocessedMemoryNetworkInput(
                self.reward,
                self.time_diff,
                self.step,
                self.not_terminal,
                state,
                next_state,
                action,
            )
        else:
            assert isinstance(self.action, torch.ByteTensor)
            return PreprocessedMemoryNetworkInput(
                self.reward,
                self.time_diff,
                self.step,
                self.not_terminal,
                state,
                next_state,
                self.action.float(),
            )


@dataclass
class ExtraData(BaseDataClass):
    mdp_id: Optional[
        np.ndarray
    ] = None  # Need to use a numpy array because torch doesn't support strings
    sequence_number: Optional[torch.Tensor] = None
    action_probability: Optional[torch.Tensor] = None
    max_num_actions: Optional[int] = None
    metrics: Optional[torch.Tensor] = None


@dataclass
class PreprocessedTrainingBatch(BaseDataClass):
    training_input: Union[
        PreprocessedBaseInput,
        PreprocessedDiscreteDqnInput,
        PreprocessedParametricDqnInput,
        PreprocessedMemoryNetworkInput,
        PreprocessedPolicyNetworkInput,
    ]
    extras: Any

    def batch_size(self):
        return self.training_input.state.size()[0]


@dataclass
class RawTrainingBatch(BaseDataClass):
    training_input: Union[
        RawBaseInput, RawDiscreteDqnInput, RawParametricDqnInput, RawPolicyNetworkInput
    ]
    extras: Any

    def batch_size(self):
        return self.training_input.state.float_features.value.size()[0]

    def preprocess(
        self,
        training_input: Union[
            PreprocessedBaseInput,
            PreprocessedDiscreteDqnInput,
            PreprocessedParametricDqnInput,
            PreprocessedMemoryNetworkInput,
            PreprocessedPolicyNetworkInput,
        ],
    ) -> PreprocessedTrainingBatch:
        return PreprocessedTrainingBatch(
            training_input=training_input, extras=self.extras
        )


@dataclass
class SingleQValue(BaseDataClass):
    q_value: torch.Tensor


@dataclass
class AllActionQValues(BaseDataClass):
    q_values: torch.Tensor


@dataclass
class CappedContinuousAction(BaseDataClass):
    """
    Continuous action in range [-1, 1], e.g., the output of DDPG actor
    """

    action: torch.Tensor


@dataclass
class MemoryNetworkOutput(BaseDataClass):
    mus: torch.Tensor
    sigmas: torch.Tensor
    logpi: torch.Tensor
    reward: torch.Tensor
    not_terminal: torch.Tensor
    last_step_lstm_hidden: torch.Tensor
    last_step_lstm_cell: torch.Tensor
    all_steps_lstm_hidden: torch.Tensor


@dataclass
class DqnPolicyActionSet(BaseDataClass):
    greedy: int
    softmax: int


@dataclass
class SacPolicyActionSet:
    greedy: torch.Tensor
    greedy_propensity: float
