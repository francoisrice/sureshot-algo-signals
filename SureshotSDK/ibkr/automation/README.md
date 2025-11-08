# Interactive Brokers Web API / Client Portal API

- Authenticate to the API
  1. Run `bin/run.sh root/conf.yaml` from `/ibkr`
  2. From a separate process, run `python3 automation/headless_auth.py`
  3. You can now use the client or check auth

Execute `bin/run.sh` in the background if possible

Authentication must be done through a browser without a VPN, preferrably Chrome

Must have Java installed (aka run from Java container...That can also automate the login process with a headless browser...)
