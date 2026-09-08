# dirigent-testing

Test doubles and pytest fixtures for writing and testing dirigent blocks.

Installing it registers the fixtures by entry point, so a block author writes no conftest.
`block_ctx` is a step context with a recording log and real storage behind it, and
`call_block` validates a config the way the engine does before making the block's first call.

`check_pack_examples` checks a pack's own example documents against its own `Contribution`
-- format, code, blocks, config schemas, and carried connections -- without importing
dirigent-core, and `assert_contribution_conforms` checks the blocks a contribution provides
are well-formed. Both return a list of human-readable issues; an empty list means it passed.
