#  ------------------------------------------------------------------------------------------
#  Copyright (c) Microsoft Corporation. All rights reserved.
#  Licensed under the MIT License (MIT). See LICENSE in the repo root for license information.
#  ------------------------------------------------------------------------------------------

import os
from typing import List, Optional
from dataclasses import dataclass, astuple, asdict

import numpy as np
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


@dataclass
class Rectangle(Element):
    center: Coordinates
    width: float
    height: float

    def __post_init__(self):
        if not isinstance(self.center, Coordinates):
            raise TypeError(f"Center must be an instance of Coordinates, not {type(self.center)}")
        if self.width < 0:
            raise ValueError(f"Width must be a positive number, but \"{self.width}\" was passed")
        if self.height < 0:
            raise ValueError(f"Height must be a positive number, but \"{self.height}\" was passed")

    def as_json(self):
        data = {}
        data["fillColor"] = str(self.fill_color)
        data["lineColor"] = str(self.line_color)
        data["type"] = "rectangle"
        data["center"] = list(astuple(self.center))
        data["center"].append(0)  # the 3rd dimension is enforced by the JSON schema
        data["width"] = self.width
        data["height"] = self.height
        return data


@dataclass
class Annotation:
    elements: Optional[List[Element]] = None
    name: str = ""
    description: str = ""

    def as_json(self):
        data = {}
        data["name"] = self.name
        data["description"] = self.description
        data["elements"] = [element.as_json() for element in self.elements]
        return data


class DigitalSlideArchive:
    def __init__(self):
        self._client = self._get_client()

    @staticmethod
    def _get_client() -> GirderClient:
        client = GirderClient(apiUrl=os.environ["GIRDER_API_URL"])
        client.authenticate(apiKey=os.environ["GIRDER_API_KEY"])
        return client

    def add_annotation(self, item_id: str, annotation: Annotation):
        response = self._client.post(
            path="annotation",
            parameters={"itemId": item_id},
            json=annotation.as_json(),
        )
        return response
