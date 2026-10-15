"""Print a machine-readable summary of evidence quality, without training a model."""
import argparse
import json
from pathlib import Path
from annotation_core import audit_annotations, DEFAULT_OUTPUT


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,default=DEFAULT_OUTPUT)
    parser.add_argument('--no-image-check',action='store_true')
    a=parser.parse_args()
    print(json.dumps(audit_annotations(a.input,not a.no_image_check),ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
