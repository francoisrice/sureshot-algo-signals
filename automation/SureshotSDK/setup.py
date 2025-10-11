from setuptools import setup, find_packages

setup(
    name="SureshotSDK",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "typing-extensions>=4.0.0",
        "pytz>=2021.1",
        "requests>=2.25.0",
    ],
    python_requires=">=3.8",
    description="Sureshot SDK for algorithmic trading automation",
    author="Sureshot Team",
)