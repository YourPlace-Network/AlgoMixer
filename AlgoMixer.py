from pyteal import *

def approval_program():
    # Global variables
    mixer_balance = Bytes("balance")
    min_deposit = Bytes("min_deposit")
    max_deposit = Bytes("max_deposit")
    min_withdrawal_delay = Bytes("min_withdrawal_delay")
    max_withdrawal_delay = Bytes("max_withdrawal_delay")
    withdrawal_window = Bytes("withdrawal_window")
    admin = Bytes("admin")
    fee_percentage = Bytes("fee_percentage")
    min_chunks = Bytes("min_chunks")
    max_chunks = Bytes("max_chunks")

    # Local variables (per user)
    deposit_amount = Bytes("deposit_amount")
    deposit_time = Bytes("deposit_time")
    withdrawal_key = Bytes("withdrawal_key")
    total_withdrawn = Bytes("total_withdrawn")
    chunks_withdrawn = Bytes("chunks_withdrawn")
    total_chunks = Bytes("total_chunks")
    next_withdrawal_time = Bytes("next_withdrawal_time")

    # Helper functions
    @Subroutine(TealType.uint64)
    def pseudo_random(seed):
        return Sha256(Concat(
            Itob(Global.latest_timestamp()),
            Itob(Global.round()),
            Itob(seed)
        ))[0:8]

    @Subroutine(TealType.uint64)
    def get_random_in_range(min_val, max_val, seed):
        random = pseudo_random(seed)
        range_size = max_val - min_val + Int(1)
        return (random % range_size) + min_val

    # Actions
    on_create = Seq([
        App.globalPut(mixer_balance, Int(0)),
        App.globalPut(min_deposit, Int(1000000)),  # 1 Algo
        App.globalPut(max_deposit, Int(100000000)),  # 100 Algo
        App.globalPut(min_withdrawal_delay, Int(3600 * 12)),  # 12 hours
        App.globalPut(max_withdrawal_delay, Int(3600 * 72)),  # 72 hours
        App.globalPut(withdrawal_window, Int(86400 * 14)),  # 14 days
        App.globalPut(admin, Txn.sender()),
        App.globalPut(fee_percentage, Int(100)),  # 1% (in basis points)
        App.globalPut(min_chunks, Int(2)),  # Minimum number of chunks
        App.globalPut(max_chunks, Int(5)),  # Maximum number of chunks
        Return(Int(1))
    ])

    # Function to handle deposits
    # Arg 0: withdrawal key (hashed)
    on_deposit = Seq([
        Assert(Txn.application_args.length() == Int(1)),
        Assert(Txn.amount() >= App.globalGet(min_deposit)),
        Assert(Txn.amount() <= App.globalGet(max_deposit)),

        # Generate random number of chunks
        num_chunks = get_random_in_range(
        App.globalGet(min_chunks),
        App.globalGet(max_chunks),
        Txn.amount()
    ),

        # Generate random initial delay
    random_delay = get_random_in_range(
        App.globalGet(min_withdrawal_delay),
        App.globalGet(max_withdrawal_delay),
        Txn.amount() + Global.latest_timestamp()
    ),

        # Store deposit info in local state
    App.localPut(Txn.sender(), deposit_amount, Txn.amount()),
    App.localPut(Txn.sender(), deposit_time, Global.latest_timestamp()),
    App.localPut(Txn.sender(), withdrawal_key, Txn.application_args[0]),
    App.localPut(Txn.sender(), total_withdrawn, Int(0)),
    App.localPut(Txn.sender(), chunks_withdrawn, Int(0)),
    App.localPut(Txn.sender(), total_chunks, num_chunks),
    App.localPut(Txn.sender(), next_withdrawal_time, Global.latest_timestamp() + random_delay),

        # Update global balance
    App.globalPut(mixer_balance, App.globalGet(mixer_balance) + Txn.amount()),

    Return(Int(1))
    ])

    # Function to handle withdrawals
    # Arg 0: original withdrawal key
    # Arg 1: receiver address
    on_withdraw = Seq([
        Assert(Txn.application_args.length() == Int(2)),

        # Load variables
        deposit_amt = App.localGet(Txn.sender(), deposit_amount),
    total_withdrawn_amt = App.localGet(Txn.sender(), total_withdrawn),
    chunks_withdrawn_count = App.localGet(Txn.sender(), chunks_withdrawn),
    total_chunks_count = App.localGet(Txn.sender(), total_chunks),
    next_time = App.localGet(Txn.sender(), next_withdrawal_time),

        # Verify time delay has passed
    Assert(Global.latest_timestamp() >= next_time),

        # Verify withdrawal is still within the valid window
    Assert(Global.latest_timestamp() <= App.localGet(Txn.sender(), deposit_time) + App.globalGet(withdrawal_window)),

        # Verify user hasn't withdrawn all chunks
    Assert(chunks_withdrawn_count < total_chunks_count),

        # Verify withdrawal key
    Assert(Sha256(Txn.application_args[0]) == App.localGet(Txn.sender(), withdrawal_key)),

        # Calculate this chunk's amount
    is_last_chunk = (chunks_withdrawn_count + Int(1) == total_chunks_count),
    chunk_amount = If(
        is_last_chunk,
        # If last chunk, withdraw remaining balance
        deposit_amt - total_withdrawn_amt,
        # Otherwise generate a random chunk size
        # This ensures the last chunk isn't predictably sized
        get_random_in_range(
            (deposit_amt / total_chunks_count) / Int(2),  # Min is half average
            (deposit_amt / total_chunks_count) * Int(2),  # Max is double average
            Global.latest_timestamp() + chunks_withdrawn_count
        )
    ),

        # Cap chunk amount to ensure we don't exceed total
    actual_chunk_amount = If(
        total_withdrawn_amt + chunk_amount > deposit_amt,
        deposit_amt - total_withdrawn_amt,
        chunk_amount
    ),

        # Calculate fee
    fee_amt = actual_chunk_amount * App.globalGet(fee_percentage) / Int(10000),
    withdrawal_amt = actual_chunk_amount - fee_amt,

        # Update local state
    App.localPut(Txn.sender(), total_withdrawn, total_withdrawn_amt + actual_chunk_amount),
    App.localPut(Txn.sender(), chunks_withdrawn, chunks_withdrawn_count + Int(1)),

        # Generate next withdrawal time if not last chunk
    next_random_delay = get_random_in_range(
        App.globalGet(min_withdrawal_delay),
        App.globalGet(max_withdrawal_delay),
        Global.latest_timestamp() + chunks_withdrawn_count
    ),
    App.localPut(
        Txn.sender(),
        next_withdrawal_time,
        If(is_last_chunk, Int(0), Global.latest_timestamp() + next_random_delay)
    ),

        # Update global balance
    App.globalPut(mixer_balance, App.globalGet(mixer_balance) - withdrawal_amt),

        # Send the funds to receiver
    receiver = Txn.application_args[1],
    InnerTxnBuilder.Begin(),
    InnerTxnBuilder.SetFields({
        TxnField.type_enum: TxnType.Payment,
        TxnField.amount: withdrawal_amt,
        TxnField.receiver: Addr(receiver),
        TxnField.fee: Int(0),  # Fee covered by the withdrawal transaction
    }),
    InnerTxnBuilder.Submit(),

    Return(Int(1))
    ])

    # Admin functions
    update_settings = Seq([
        Assert(Txn.sender() == App.globalGet(admin)),

        # Update settings based on which parameter is being updated
        Cond(
            [Txn.application_args[0] == Bytes("min_deposit"),
             App.globalPut(min_deposit, Btoi(Txn.application_args[1]))],
            [Txn.application_args[0] == Bytes("max_deposit"),
             App.globalPut(max_deposit, Btoi(Txn.application_args[1]))],
            [Txn.application_args[0] == Bytes("min_withdrawal_delay"),
             App.globalPut(min_withdrawal_delay, Btoi(Txn.application_args[1]))],
            [Txn.application_args[0] == Bytes("max_withdrawal_delay"),
             App.globalPut(max_withdrawal_delay, Btoi(Txn.application_args[1]))],
            [Txn.application_args[0] == Bytes("withdrawal_window"),
             App.globalPut(withdrawal_window, Btoi(Txn.application_args[1]))],
            [Txn.application_args[0] == Bytes("fee_percentage"),
             App.globalPut(fee_percentage, Btoi(Txn.application_args[1]))],
            [Txn.application_args[0] == Bytes("min_chunks"),
             App.globalPut(min_chunks, Btoi(Txn.application_args[1]))],
            [Txn.application_args[0] == Bytes("max_chunks"),
             App.globalPut(max_chunks, Btoi(Txn.application_args[1]))],
        ),

        Return(Int(1))
    ])

    # Main router
    program = Cond(
        [Txn.application_id() == Int(0), on_create],
        [Txn.on_completion() == OnComplete.OptIn, Return(Int(1))],
        [Txn.on_completion() == OnComplete.CloseOut, Return(Int(1))],
        [Txn.on_completion() == OnComplete.UpdateApplication, Return(Int(0))],
        [Txn.on_completion() == OnComplete.DeleteApplication, Return(Int(0))],
        [Txn.application_args[0] == Bytes("deposit"), on_deposit],
        [Txn.application_args[0] == Bytes("withdraw"), on_withdraw],
        [Txn.application_args[0] == Bytes("update_settings"), update_settings],
    )

    return program

def clear_state_program():
    return Return(Int(1))

if __name__ == "__main__":
    with open("mixer_approval.teal", "w") as f:
        compiled = compileTeal(approval_program(), Mode.Application, version=6)
        f.write(compiled)

    with open("mixer_clear_state.teal", "w") as f:
        compiled = compileTeal(clear_state_program(), Mode.Application, version=6)
        f.write(compiled)