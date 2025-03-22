#!/bin/bash

if [[ $(uname) != "Darwin" ]]; then
  echo "Must run on macOS"
  exit 1
fi

# Set up Python environment
python3 -m venv venv
source venv/bin/activate
pip3 install pyteal
pip3 install py-algorand-sdk

# Set up Algorand sandbox
brew install docker-compose
git clone https://github.com/algorand/sandbox.git
cd sandbox
./sandbox up testnet

# Set up Algorand CLI
brew install algorand-devrel/tap/goal

# Compile PyTeal code
python AlgoMixer.py

# Create Testing Accounts
goal account new -d ~/node/data
goal account new -d ~/node/data
goal account list -d ~/node/data

# Fund the Testnet accounts
# https://bank.testnet.algorand.network/

# Deploy the smart contract
# Create the application
goal app create --creator <YOUR_ACCOUNT_ADDRESS> \
  --approval-prog mixer_approval.teal \
  --clear-prog mixer_clear_state.teal \
  --global-byteslices 1 \
  --global-ints 8 \
  --local-byteslices 1 \
  --local-ints 6 \
  --app-arg "str:init" \
  -d ~/node/data

# Opt into the application
goal app optin --app-id <APP_ID> \
  --from <USER_ACCOUNT_ADDRESS> \
  -d ~/node/data

# Make a deposit
# Generate a random key
WITHDRAWAL_KEY=$(openssl rand -hex 16)
echo "Save this withdrawal key: $WITHDRAWAL_KEY"
# Hash the key (using Python)
python -c "import hashlib; print(hashlib.sha256('$WITHDRAWAL_KEY'.encode()).hexdigest())"
goal app call --app-id <APP_ID> \
  --from <USER_ACCOUNT_ADDRESS> \
  --app-arg "str:deposit" \
  --app-arg "addr:<HASHED_WITHDRAWAL_KEY>" \
  --amount 5000000 \
  -d ~/node/data

# Wait for the random delay period
goal app read --app-id <APP_ID> \
  --local --from <USER_ACCOUNT_ADDRESS> \
  -d ~/node/data

# Withdraw a chunk
goal app call --app-id <APP_ID> \
  --from <USER_ACCOUNT_ADDRESS> \
  --app-arg "str:withdraw" \
  --app-arg "str:$WITHDRAWAL_KEY" \
  --app-arg "addr:<RECIPIENT_ADDRESS>" \
  -d ~/node/data

# Repeat withdrawls
goal app read --app-id <APP_ID> \
  --local --from <USER_ACCOUNT_ADDRESS> \
  -d ~/node/data