#!/bin/bash
# Installed once at template build time — available instantly in every sandbox
pip install --quiet \
    pandas>=2.2 \
    numpy>=1.26 \
    matplotlib>=3.9 \
    seaborn>=0.13 \
    scikit-learn>=1.5 \
    scipy>=1.13 \
    biopython \
    pysam
