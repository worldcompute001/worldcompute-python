"""World Compute command-line interface."""
import argparse

from . import molmo


def main():
    parser = argparse.ArgumentParser(prog='worldcompute')
    commands = parser.add_subparsers(dest='command', required=True)
    run = commands.add_parser('run', help='Run a robot harness')
    models = run.add_subparsers(dest='model', required=True)
    model = models.add_parser('molmo', help='Run MolmoAct2 on the SO100')
    molmo.add_arguments(model)
    args = parser.parse_args()
    molmo.run_args(model, args)
