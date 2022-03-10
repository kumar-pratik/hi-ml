#  ------------------------------------------------------------------------------------------
#  Copyright (c) Microsoft Corporation. All rights reserved.
#  Licensed under the MIT License (MIT). See LICENSE in the repo root for license information.
#  ------------------------------------------------------------------------------------------

import os
from typing import List, Optional
from dataclasses import dataclass, astuple, asdict

import numpy as np
import pandas as pd
from girder_client import GirderClient


@dataclass
class Color:
    red: int
    green: int
    blue: int
    alpha: int

    def __post_init__(self):
        array = np.asarray(self)
        if (array < 0).any() or (array > 255).any():
            raise ValueError(f"All RGBA components must be between 0 and 255, but {astuple(self)} were passed")

    def __array__(self):
        return np.array(self.components, dtype=int)

    @property
    def components(self):
        return astuple(self)

    def __str__(self):
        return f"rgba{astuple(self)}"


class Transparent(Color):
    def __init__(self):
        super().__init__(0, 0, 0, 0)


@dataclass
class Element:
    label: str
    fill_color: Color
    line_color: Color


@dataclass
class Coordinates:
    x: float
    y: float

    def __post_init__(self):
        try:
            float(self.x)
            float(self.y)
        except ValueError as e:
            raise TypeError(f"Error converting coordinates to float: \"{asdict(self)}\"") from e

    def __array__(self):
        return np.asarray(astuple(self))


@dataclass
class Rectangle(Element):
    top_left: Coordinates
    width: float
    height: float

    def __post_init__(self):
        if not isinstance(self.top_left, Coordinates):
            raise TypeError(f"Points must be instances of Coordinates, not {type(self.top_left)}")
        if self.width < 0:
            raise ValueError(f"Width must be a positive number, but \"{self.width}\" was passed")
        if self.height < 0:
            raise ValueError(f"Height must be a positive number, but \"{self.height}\" was passed")

    @property
    def center(self):
        size = np.array((self.width, self.height))
        return np.asarray(self.top_left) + size / 2

    def as_json(self):
        data = {}
        data["fillColor"] = str(self.fill_color)
        data["lineColor"] = str(self.line_color)
        data["type"] = "rectangle"
        data["center"] = self.center.tolist() + [0]
        data["width"] = float(self.width)
        data["height"] = float(self.height)
        data["label"] = {"value": self.label}
        return data


@dataclass
class Point(Element):
    center: Coordinates

    def __post_init__(self):
        if not isinstance(self.center, Coordinates):
            raise TypeError(f"Center must be an instance of Coordinates, not {type(self.center)}")

    def as_json(self):
        data = {}
        data["fillColor"] = str(self.fill_color)
        data["lineColor"] = str(self.line_color)
        data["type"] = "point"
        data["center"] = list(astuple(self.center)) + [0]
        data["label"] = {"value": self.label}
        return data


@dataclass
class Annotation:
    name: str
    elements: Optional[List[Element]] = None
    description: str = ""

    def __post_init__(self):
        if not self.name:
            # This is enforced by the JSON schema
            raise ValueError('The annotation name cannot be empty')
        if self.elements is None:
            self.elements = []

    def as_json(self):
        data = {}
        data["name"] = self.name
        data["description"] = self.description
        data["elements"] = [element.as_json() for element in self.elements]
        return data


class DigitalSlideArchive:
    def __init__(
            self,
            api_url: Optional[str] = None,
            api_key: Optional[str] = None,
            ):
        self._client = self._get_client(api_url, api_key)

    @staticmethod
    def _get_client(api_url: Optional[str], api_key: Optional[str]) -> GirderClient:
        client = GirderClient(apiUrl=os.environ["GIRDER_API_URL"] if api_url is None else api_url)
        client.authenticate(apiKey=os.environ["GIRDER_API_KEY"] if api_key is None else api_key)
        return client

    def add_annotation(self, item_id: str, annotation: Annotation):
        response = self._client.post(
            path="annotation",
            parameters={"itemId": item_id},
            json=annotation.as_json(),
        )
        return response

    def get_file_id(self, folder_name, file_name):
        folders = self._client.get('folder', {'text': folder_name})
        assert len(folders) == 1
        folder_id = folders[0]['_id']
        iterator = self._client.listItem(folder_id, name=file_name)
        matches = list(iterator)
        assert matches, f'File {file_name} not found in folder {folder_name}'
        assert len(matches) == 1
        return matches[0]['_id']
