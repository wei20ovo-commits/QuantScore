"""Bounded production browser verification; inherits the existing click budget."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--label',required=True,choices=['baseline','release','identity'])
    parser.add_argument('--wake-once',action='store_true')
    parser.add_argument('--identity-only',action='store_true')
    args=parser.parse_args()
    from tools import product_public_verify as probe
    probe.BASELINE=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip()
    probe.OUT=ROOT/'outputs/final_engineering'/('public_'+args.label)
    if (probe.OUT/'verification.json').exists():raise RuntimeError('Refusing to overwrite public evidence')
    probe.main()

if __name__=='__main__':main()
