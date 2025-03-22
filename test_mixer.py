from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.future import transaction
import base64
import hashlib
import time
import random
import os

# Connect to Algorand node
algod_address = "http://localhost:4001"
algod_token = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
algod_client = algod.AlgodClient(algod_token, algod_address)

# Replace with your mnemonics
creator_mnemonic = "your creator mnemonic here"
user_mnemonic = "your user mnemonic here"
recipient_mnemonic = "your recipient mnemonic here"

# Generate accounts from mnemonics
creator_private_key = mnemonic.to_private_key(creator_mnemonic)
creator_address = account.address_from_private_key(creator_private_key)

user_private_key = mnemonic.to_private_key(user_mnemonic)
user_address = account.address_from_private_key(user_private_key)

recipient_private_key = mnemonic.to_private_key(recipient_mnemonic)
recipient_address = account.address_from_private_key(recipient_private_key)

# Read TEAL files
with open("mixer_approval.teal", "r") as f:
    approval_program = f.read()

with open("mixer_clear_state.teal", "r") as f:
    clear_state_program = f.read()

# Compile TEAL programs
approval_result = algod_client.compile(approval_program)
approval_binary = base64.b64decode(approval_result["result"])

clear_result = algod_client.compile(clear_state_program)
clear_binary = base64.b64decode(clear_result["result"])

# Helper function for waiting for a transaction to be confirmed
def wait_for_confirmation(client, txid):
    last_round = client.status().get("last-round")
    while True:
        txinfo = client.pending_transaction_info(txid)
        if txinfo.get("confirmed-round", 0) > 0:
            print("Transaction confirmed in round", txinfo.get("confirmed-round"))
            return txinfo
        else:
            print("Waiting for confirmation...")
            last_round += 1
            client.status_after_block(last_round)

# Helper function for creating a transaction
def create_transaction(sender, receiver, amount, note, sp):
    return transaction.PaymentTxn(
        sender=sender,
        sp=sp,
        receiver=receiver,
        amt=amount,
        note=note
    )

# Deploy the application
def deploy_app():
    # Get suggested parameters
    params = algod_client.suggested_params()

    # Create unsigned transaction
    txn = transaction.ApplicationCreateTxn(
        sender=creator_address,
        sp=params,
        on_complete=transaction.OnComplete.NoOpOC,
        approval_program=approval_binary,
        clear_program=clear_binary,
        global_schema=transaction.StateSchema(num_uints=8, num_byte_slices=1),
        local_schema=transaction.StateSchema(num_uints=6, num_byte_slices=1)
    )

    # Sign transaction
    signed_txn = txn.sign(creator_private_key)

    # Submit transaction
    txid = algod_client.send_transaction(signed_txn)
    print(f"Deployed app with txid: {txid}")

    # Wait for confirmation
    wait_for_confirmation(algod_client, txid)

    # Get the application ID
    transaction_response = algod_client.pending_transaction_info(txid)
    app_id = transaction_response["application-index"]
    print(f"Created app with ID: {app_id}")

    return app_id

# Opt in to the application
def opt_in_app(app_id, private_key, address):
    # Get suggested parameters
    params = algod_client.suggested_params()

    # Create unsigned transaction
    txn = transaction.ApplicationOptInTxn(
        sender=address,
        sp=params,
        index=app_id
    )

    # Sign transaction
    signed_txn = txn.sign(private_key)

    # Submit transaction
    txid = algod_client.send_transaction(signed_txn)
    print(f"Opted in to app with txid: {txid}")

    # Wait for confirmation
    wait_for_confirmation(algod_client, txid)

# Make a deposit
def deposit(app_id, amount, private_key, address):
    # Generate a random withdrawal key
    withdrawal_key = os.urandom(16).hex()
    print(f"Generated withdrawal key: {withdrawal_key}")

    # Hash the withdrawal key
    withdrawal_key_hash = hashlib.sha256(withdrawal_key.encode()).digest()

    # Get suggested parameters
    params = algod_client.suggested_params()

    # Create application call transaction
    app_call_txn = transaction.ApplicationCallTxn(
        sender=address,
        sp=params,
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=["deposit", withdrawal_key_hash]
    )

    # Create payment transaction
    pay_txn = transaction.PaymentTxn(
        sender=address,
        sp=params,
        receiver=algod_client.application_info(app_id)["params"]["creator"],
        amt=amount
    )

    # Group transactions
    gid = transaction.calculate_group_id([app_call_txn, pay_txn])
    app_call_txn.group = gid
    pay_txn.group = gid

    # Sign transactions
    signed_app_call_txn = app_call_txn.sign(private_key)
    signed_pay_txn = pay_txn.sign(private_key)

    # Submit transactions
    txid = algod_client.send_transactions([signed_app_call_txn, signed_pay_txn])
    print(f"Deposited with txid: {txid}")

    # Wait for confirmation
    wait_for_confirmation(algod_client, txid)

    return withdrawal_key

# Check local state
def check_local_state(app_id, address):
    app_info = algod_client.account_application_info(address, app_id)
    local_state = app_info["app-local-state"]["key-value"]

    state_dict = {}
    for item in local_state:
        key = base64.b64decode(item["key"]).decode("utf-8")
        if item["value"]["type"] == 1:  # uint
            state_dict[key] = item["value"]["uint"]
        else:  # bytes
            state_dict[key] = base64.b64decode(item["value"]["bytes"]).hex()

    return state_dict

# Withdraw
def withdraw(app_id, withdrawal_key, private_key, address):
    # Get suggested parameters
    params = algod_client.suggested_params()

    # Create unsigned transaction
    txn = transaction.ApplicationCallTxn(
        sender=address,
        sp=params,
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=["withdraw", withdrawal_key, recipient_address]
    )

    # Sign transaction
    signed_txn = txn.sign(private_key)

    # Submit transaction
    txid = algod_client.send_transaction(signed_txn)
    print(f"Withdrew with txid: {txid}")

    # Wait for confirmation
    wait_for_confirmation(algod_client, txid)

# Main testing flow
def main():
    # Deploy app
    app_id = deploy_app()

    # Opt in
    opt_in_app(app_id, user_private_key, user_address)

    # Make deposit
    amount = 10000000  # 10 Algos
    withdrawal_key = deposit(app_id, amount, user_private_key, user_address)

    # Check local state to see next withdrawal time
    local_state = check_local_state(app_id, user_address)
    print(f"Local state after deposit: {local_state}")

    # Wait until we can withdraw
    current_time = int(time.time())
    next_withdrawal_time = local_state["next_withdrawal_time"]

    if current_time < next_withdrawal_time:
        wait_time = next_withdrawal_time - current_time
        print(f"Waiting {wait_time} seconds until we can withdraw...")
        time.sleep(wait_time)

    # Withdraw all chunks
    total_chunks = local_state["total_chunks"]

    for i in range(total_chunks):
        print(f"Withdrawing chunk {i+1} of {total_chunks}")

        # Withdraw
        withdraw(app_id, withdrawal_key, user_private_key, user_address)

        # Check local state
        local_state = check_local_state(app_id, user_address)
        print(f"Local state after withdrawal: {local_state}")

        # If not the last chunk, wait for the next withdrawal time
        if i < total_chunks - 1:
            current_time = int(time.time())
            next_withdrawal_time = local_state["next_withdrawal_time"]

            if current_time < next_withdrawal_time:
                wait_time = next_withdrawal_time - current_time
                print(f"Waiting {wait_time} seconds until next withdrawal...")
                time.sleep(wait_time)

if __name__ == "__main__":
    main()