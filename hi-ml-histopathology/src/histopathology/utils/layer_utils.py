#  ------------------------------------------------------------------------------------------
#  Copyright (c) Microsoft Corporation. All rights reserved.
#  Licensed under the MIT License (MIT). See LICENSE in the repo root for license information.
#  ------------------------------------------------------------------------------------------

from typing import Tuple

from torch import as_tensor, device, nn, no_grad, prod, rand
from torch.hub import load_state_dict_from_url
from torchvision.transforms import Normalize


def get_imagenet_preprocessing() -> nn.Module:
    return Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])


def setup_feature_extractor(pretrained_model: nn.Module,
                            input_dim: Tuple[int, int, int]) -> Tuple[nn.Module, int]:
    try:
        # Attempt to auto-detect final classification layer:
        num_features: int = pretrained_model.fc.in_features  # type: ignore
        pretrained_model.fc = nn.Flatten()
        feature_extractor = pretrained_model
    except AttributeError:
        # Otherwise fallback to sequence of child modules:
        layers = list(pretrained_model.children())[:-1]
        layers.append(nn.Flatten())  # flatten non-batch dims in case of spatial feature maps
        feature_extractor = nn.Sequential(*layers)
        with no_grad():
            feature_shape = feature_extractor(rand(1, *input_dim)).shape
        num_features = int(prod(as_tensor(feature_shape)).item())
    # fix weights, no fine-tuning
    for param in feature_extractor.parameters():
        param.requires_grad = False
    return feature_extractor, num_features


def load_weights_to_model(weights_url: str, model: nn.Module) -> nn.Module:
    """
    Load weights to the histoSSL model from the given URL
    https://github.com/ozanciga/self-supervised-histopathology
    """
    map_location = device('cpu')
    state = load_state_dict_from_url(weights_url, map_location=map_location)
    state_dict = state['state_dict']
    model_dict = model.state_dict()

    new_weights = {}
    for key, value in state_dict.items():
        model_key = key.replace('model.', '').replace('resnet.', '')
        if model_key in model_dict:
            new_weights[model_key] = value
    if len(new_weights) == 0:
        raise RuntimeError("Weights could not be loaded.")
    model_dict.update(new_weights)  # type: ignore

    model.load_state_dict(model_dict)  # type: ignore
    return model
