from setuptools import setup, find_packages

setup(
    name="neuron",
    version="0.1.0",
    author="Bernard Dario",
    description="NEURON — Distributed Computing Platform",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    packages=find_packages(),
    python_requires=">=3.8",
    entry_points={
        "console_scripts": [
            "neuron=neuron.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Topic :: System :: Distributed Computing",
    ],
)
