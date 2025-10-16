from setuptools import setup, find_packages
import os

# Read requirements from requirements.txt
def read_requirements():
    requirements = []
    req_file = os.path.join(os.path.dirname(__file__), 'requirements.txt')
    if os.path.exists(req_file):
        with open(req_file) as f:
            for line in f:
                line = line.strip()
                # Skip empty lines, comments, and optional dependencies
                if line and not line.startswith('#') and not line.startswith('hvac'):
                    requirements.append(line)
    return requirements

setup(
    name="SureshotSDK",
    version="0.1.0",
    description="Shared SDK for Sureshot algorithmic trading strategies",
    author="Sureshot Team",
    packages=find_packages(exclude=["tests", "tests.*"]),
    install_requires=read_requirements(),
    python_requires=">=3.8",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
)