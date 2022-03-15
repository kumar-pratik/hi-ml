#  ------------------------------------------------------------------------------------------
#  Copyright (c) Microsoft Corporation. All rights reserved.
#  Licensed under the MIT License (MIT). See LICENSE in the repo root for license information.
#  ------------------------------------------------------------------------------------------
import argparse
import pandas as pd
import json
import logging
from health_azure.utils import is_local_rank_zero

from health_ml.utils.common_utils import logging_to_stdout


def dump_dataset_csv_from_wsi_ids(datalist_json: str, dataset_csv: str, dest_dataset_csv: str) -> None:

    # get target wsi ids
    with open(datalist_json, "r") as f:
        slides = json.load(f)
    wsi_ids = [slide['image'].split(".")[0] for slide in slides["training"]]
    wsi_ids

    # select corresponding tiles from dataset
    df = pd.read_csv(dataset_csv)
    df.to_csv(dataset_csv, index=False)
    df.loc[df['slide_id'].isin(wsi_ids)].to_csv(dest_dataset_csv, index=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    logging_to_stdout("INFO" if is_local_rank_zero() else "ERROR")
    parser.add_argument("--datalist-json", type=str, default="panda/datalist_20.json")
    parser.add_argument("--dataset-csv", type=str, default="panda/dataset_20.csv")
    parser.add_argument("--dest-dataset-csv", type=str, default="panda/dataset_20.csv")
    args = parser.parse_args()
    logging.info(f"Selecting target WSI ids from {args.datalist_json}  and wrinting them to {args.dest_dataset_csv}")
    dump_dataset_csv_from_wsi_ids(args.datalist_json, args.dataset_csv, args.dest_dataset_csv)
