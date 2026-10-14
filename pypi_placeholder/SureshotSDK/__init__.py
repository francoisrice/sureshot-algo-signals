raise ImportError(
    "This PyPI package only reserves the SureshotSDK name. The real SureshotSDK is distributed "
    "privately: install it from the vendor/ folder of your Sureshot bundle with "
    "`pip install --require-hashes --only-binary :all: -r requirements.txt`."
)
