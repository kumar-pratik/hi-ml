#  ------------------------------------------------------------------------------------------
#  Copyright (c) Microsoft Corporation. All rights reserved.
#  Licensed under the MIT License (MIT). See LICENSE in the repo root for license information.
#  ------------------------------------------------------------------------------------------

import os
from typing import Any, Callable, Dict, Iterable, List, Optional, Type, Tuple
from unittest.mock import MagicMock

import pytest
import torch
from torch import Tensor, argmax, nn, rand, randint, randn, round, stack, allclose
from torch.utils.data._utils.collate import default_collate
from torchvision.models import resnet18

from health_ml.lightning_container import LightningContainer
from health_ml.networks.layers.attention_layers import AttentionLayer


from histopathology.configs.classification.DeepSMILECrck import DeepSMILECrck
from histopathology.configs.classification.DeepSMILEPanda import DeepSMILEPanda
from histopathology.datamodules.base_module import TilesDataModule
from histopathology.datasets.base_dataset import TilesDataset
from histopathology.datasets.default_paths import PANDA_TILES_DATASET_DIR, TCGA_CRCK_DATASET_DIR
from histopathology.models.deepmil import DeepMILModule
from histopathology.models.encoders import IdentityEncoder, ImageNetEncoder, TileEncoder
from histopathology.utils.naming import MetricsKey, ResultsKey


def get_supervised_imagenet_encoder() -> TileEncoder:
    return ImageNetEncoder(feature_extraction_model=resnet18, tile_size=224)


def get_attention_pooling_layer(num_encoding: int = 512,
                                pool_out_dim: int = 1) -> Tuple[Type[nn.Module], int]:

    pool_hidden_dim = 5  # different dimensions get tested in test_attentionlayers.py
    pooling_layer = AttentionLayer(num_encoding,
                                   pool_hidden_dim,
                                   pool_out_dim)

    num_features = num_encoding * pool_out_dim
    return pooling_layer, num_features


def _test_lightningmodule(
    n_classes: int,
    batch_size: int,
    max_bag_size: int,
    pool_out_dim: int,
    dropout_rate: Optional[float],
) -> None:

    assert n_classes > 0

    # hard-coded here to avoid test explosion; correctness of other encoders is tested elsewhere
    encoder = get_supervised_imagenet_encoder()

    # hard-coded here to avoid test explosion; correctness of other pooling layers is tested elsewhere
    pooling_layer, num_features = get_attention_pooling_layer(pool_out_dim=pool_out_dim)

    module = DeepMILModule(
        encoder=encoder,
        label_column="label",
        n_classes=n_classes,
        pooling_layer=pooling_layer,
        num_features=num_features,
        dropout_rate=dropout_rate,
    )

    bag_images = rand([batch_size, max_bag_size, *module.encoder.input_dim])
    bag_labels_list = []
    bag_logits_list = []
    bag_attn_list = []
    for bag in bag_images:
        if n_classes > 1:
            labels = randint(n_classes, size=(max_bag_size,))
        else:
            labels = randint(n_classes + 1, size=(max_bag_size,))
        bag_labels_list.append(module.get_bag_label(labels))
        logit, attn = module(bag)
        assert logit.shape == (1, n_classes)
        assert attn.shape == (pool_out_dim, max_bag_size)
        bag_logits_list.append(logit.view(-1))
        bag_attn_list.append(attn)

    bag_logits = stack(bag_logits_list)
    bag_labels = stack(bag_labels_list).view(-1)

    assert bag_logits.shape[0] == (batch_size)
    assert bag_labels.shape[0] == (batch_size)

    if module.n_classes > 1:
        loss = module.loss_fn(bag_logits, bag_labels)
    else:
        loss = module.loss_fn(bag_logits.squeeze(1), bag_labels.float())

    assert loss > 0
    assert loss.shape == ()

    probs = module.activation_fn(bag_logits)
    assert ((probs >= 0) & (probs <= 1)).all()

    if n_classes > 1:
        predlabels = argmax(probs, dim=1)
    else:
        predlabels = round(probs)

    predlabels = predlabels.view(-1, 1)
    assert predlabels.shape[0] == batch_size
    assert probs.shape == (batch_size, n_classes)

    bag_labels = bag_labels.view(-1, 1)
    if n_classes == 1:
        probs = probs.squeeze(dim=1)
    for metric_name, metric_object in module.train_metrics.items():
        if metric_name == MetricsKey.CONF_MATRIX:
            continue
        score = metric_object(probs, bag_labels.view(batch_size,))
        assert torch.all(score >= 0)
        assert torch.all(score <= 1)


@pytest.mark.parametrize("n_classes", [1, 3])
@pytest.mark.parametrize("batch_size", [1, 15])
@pytest.mark.parametrize("max_bag_size", [1, 7])
@pytest.mark.parametrize("pool_out_dim", [1, 6])
@pytest.mark.parametrize("dropout_rate", [None, 0.5])
def test_lightningmodule_attention(
    n_classes: int,
    batch_size: int,
    max_bag_size: int,
    pool_out_dim: int,
    dropout_rate: Optional[float],
) -> None:
    _test_lightningmodule(n_classes=n_classes,
                          batch_size=batch_size,
                          max_bag_size=max_bag_size,
                          pool_out_dim=pool_out_dim,
                          dropout_rate=dropout_rate)


def validate_metric_inputs(scores: torch.Tensor, labels: torch.Tensor) -> None:
    def is_integral(x: torch.Tensor) -> bool:
        return (x == x.long()).all()  # type: ignore

    assert labels.shape == (scores.shape[0], )
    assert torch.is_floating_point(scores), "Received scores with integer dtype"
    assert not is_integral(scores), "Received scores with integral values"
    assert is_integral(labels), "Received labels with floating-point values"


def add_callback(fn: Callable, callback: Callable) -> Callable:
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        callback(*args, **kwargs)
        return fn(*args, **kwargs)
    return wrapper


@pytest.mark.parametrize("n_classes", [1, 3])
def test_metrics(n_classes: int) -> None:
    input_dim = (128,)

    # hard-coded here to avoid test explosion; correctness of other pooling layers is tested elsewhere
    pooling_layer, num_features = get_attention_pooling_layer(num_encoding=input_dim[0],
                                                              pool_out_dim=1)

    module = DeepMILModule(
        encoder=IdentityEncoder(input_dim=input_dim),
        label_column=TilesDataset.LABEL_COLUMN,
        n_classes=n_classes,
        pooling_layer=pooling_layer,
        num_features=num_features
    )

    # Patching to enable running the module without a Trainer object
    module.trainer = MagicMock(world_size=1)  # type: ignore
    module.log = MagicMock()  # type: ignore

    batch_size = 20
    bag_size = 5
    if n_classes > 1:
        class_weights = torch.rand(n_classes)
    else:
        class_weights = torch.tensor([0.8, 0.2])
    bags: List[Dict] = []
    for slide_idx in range(batch_size):
        bag_label = torch.multinomial(class_weights, 1)
        sample: Dict[str, Iterable] = {
            TilesDataset.SLIDE_ID_COLUMN: [str(slide_idx)] * bag_size,
            TilesDataset.TILE_ID_COLUMN: [f"{slide_idx}-{tile_idx}"
                                          for tile_idx in range(bag_size)],
            TilesDataset.IMAGE_COLUMN: rand(bag_size, *input_dim),
            TilesDataset.LABEL_COLUMN: bag_label.expand(bag_size),
        }
        sample[TilesDataset.PATH_COLUMN] = [tile_id + '.png'
                                            for tile_id in sample[TilesDataset.TILE_ID_COLUMN]]
        bags.append(sample)
    batch = default_collate(bags)

    # ================
    # Test that the module metrics match manually computed metrics with the correct inputs
    module_metrics_dict = module.test_metrics
    independent_metrics_dict = module.get_metrics()

    # Patch the metrics to check that the inputs are valid. In particular, test that the scores
    # do not have integral values, which would suggest that hard labels were passed instead.
    for metric_obj in module_metrics_dict.values():
        metric_obj.update = add_callback(metric_obj.update, validate_metric_inputs)

    results = module.test_step(batch, 0)
    predicted_probs = results[ResultsKey.PROB]
    true_labels = results[ResultsKey.TRUE_LABEL]

    for key, metric_obj in module_metrics_dict.items():
        value = metric_obj.compute()
        expected_value = independent_metrics_dict[key](predicted_probs, true_labels.view(batch_size,))
        assert torch.allclose(value, expected_value), f"Discrepancy in '{key}' metric"


def move_batch_to_expected_device(batch: Dict[str, List], use_gpu: bool) -> Dict:
    device = "cuda" if use_gpu else "cpu"
    return {
        key: [
            value.to(device) if isinstance(value, Tensor) else value for value in values
        ]
        for key, values in batch.items()
    }


CONTAINER_DATASET_DIR = {
    DeepSMILEPanda: PANDA_TILES_DATASET_DIR,
    DeepSMILECrck: TCGA_CRCK_DATASET_DIR,
}


@pytest.mark.parametrize("container_type", [DeepSMILEPanda,
                                            DeepSMILECrck])
@pytest.mark.parametrize("use_gpu", [True, False])
def test_container(container_type: Type[LightningContainer], use_gpu: bool) -> None:
    dataset_dir = CONTAINER_DATASET_DIR[container_type]
    if not os.path.isdir(dataset_dir):
        pytest.skip(
            f"Dataset for container {container_type.__name__} "
            f"is unavailable: {dataset_dir}"
        )
    if container_type is DeepSMILECrck:
        container = DeepSMILECrck(encoder_type=ImageNetEncoder.__name__)
    elif container_type is DeepSMILEPanda:
        container = DeepSMILEPanda(encoder_type=ImageNetEncoder.__name__)
    else:
        container = container_type()

    container.setup()

    data_module: TilesDataModule = container.get_data_module()  # type: ignore
    data_module.max_bag_size = 10
    module = container.create_model()
    if use_gpu:
        module.cuda()

    train_data_loader = data_module.train_dataloader()
    for batch_idx, batch in enumerate(train_data_loader):
        batch = move_batch_to_expected_device(batch, use_gpu)
        loss = module.training_step(batch, batch_idx)
        loss.retain_grad()
        loss.backward()
        assert loss.grad is not None
        assert loss.shape == ()
        assert isinstance(loss, Tensor)
        break

    val_data_loader = data_module.val_dataloader()
    for batch_idx, batch in enumerate(val_data_loader):
        batch = move_batch_to_expected_device(batch, use_gpu)
        loss = module.validation_step(batch, batch_idx)
        assert loss.shape == ()  # noqa
        assert isinstance(loss, Tensor)
        break

    test_data_loader = data_module.test_dataloader()
    for batch_idx, batch in enumerate(test_data_loader):
        batch = move_batch_to_expected_device(batch, use_gpu)
        outputs_dict = module.test_step(batch, batch_idx)
        loss = outputs_dict[ResultsKey.LOSS]  # noqa
        assert loss.shape == ()
        assert isinstance(loss, Tensor)
        break


def test_class_weights_binary() -> None:
    class_weights = Tensor([0.5, 3.5])
    n_classes = 1

    # hard-coded here to avoid test explosion; correctness of other pooling layers is tested elsewhere
    pooling_layer, num_features = get_attention_pooling_layer(pool_out_dim=1)

    module = DeepMILModule(
        encoder=get_supervised_imagenet_encoder(),
        label_column="label",
        n_classes=n_classes,
        pooling_layer=pooling_layer,
        num_features=num_features,
        class_weights=class_weights,
    )
    logits = Tensor(randn(1, n_classes))
    bag_label = randint(n_classes + 1, size=(1,))

    pos_weight = Tensor([class_weights[1] / (class_weights[0] + 1e-5)])
    loss_weighted = module.loss_fn(logits.squeeze(1), bag_label.float())
    criterion_unweighted = nn.BCEWithLogitsLoss()
    loss_unweighted = criterion_unweighted(logits.squeeze(1), bag_label.float())
    if bag_label.item() == 1:
        assert allclose(loss_weighted, pos_weight * loss_unweighted)
    else:
        assert allclose(loss_weighted, loss_unweighted)


def test_class_weights_multiclass() -> None:
    class_weights = Tensor([0.33, 0.33, 0.33])
    n_classes = 3

    # hard-coded here to avoid test explosion; correctness of other pooling layers is tested elsewhere
    pooling_layer, num_features = get_attention_pooling_layer(pool_out_dim=1)

    module = DeepMILModule(
        encoder=get_supervised_imagenet_encoder(),
        label_column="label",
        n_classes=n_classes,
        pooling_layer=pooling_layer,
        num_features=num_features,
        class_weights=class_weights,
    )
    logits = Tensor(randn(1, n_classes))
    bag_label = randint(n_classes, size=(1,))

    loss_weighted = module.loss_fn(logits, bag_label)
    criterion_unweighted = nn.CrossEntropyLoss()
    loss_unweighted = criterion_unweighted(logits, bag_label)
    # The weighted and unweighted loss functions give the same loss values for batch_size = 1.
    # https://stackoverflow.com/questions/67639540/pytorch-cross-entropy-loss-weights-not-working
    # TODO: the test should reflect actual weighted loss operation for the class weights after
    # batch_size > 1 is implemented.
    assert allclose(loss_weighted, loss_unweighted)
