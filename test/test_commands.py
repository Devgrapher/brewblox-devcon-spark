"""
Tests brewblox_devcon_spark.commands
"""

import pytest
from brewblox_devcon_spark import commands

TESTED = commands.__name__


@pytest.fixture
def write_value_args():
    return dict(
        object_id=[127, 7],
        type=6,
        size=10,
        data=bytes([0x0F]*10))


@pytest.fixture
def write_value_req(write_value_args):
    req = write_value_args.copy()
    req['opcode'] = 2
    return req


@pytest.fixture
def write_value_resp(write_value_args):
    return dict(
        errcode=commands.ErrorcodeEnum.OK,
        type=write_value_args['type'],
        size=write_value_args['size'],
        data=write_value_args['data']
    )


def test_index():
    index = commands.CommandIndex()
    for cmd_name in [
        'READ_VALUE',
        'WRITE_VALUE',
        'CREATE_OBJECT',
        'DELETE_OBJECT',
        'LIST_OBJECTS',
        'FREE_SLOT',
        'CREATE_PROFILE',
        'DELETE_PROFILE',
        'ACTIVATE_PROFILE',
        'LOG_VALUES',
        'RESET',
        'FREE_SLOT_ROOT',
        'LIST_PROFILES',
        'READ_SYSTEM_VALUE',
        'WRITE_SYSTEM_VALUE',
    ]:
        command = index.identify(cmd_name)
        assert command.name == cmd_name
        assert command.opcode
        assert command.request
        assert command.response

    with pytest.raises(KeyError):
        index.identify('UNUSED')


def test_variable_id_length(write_value_args):

    command = commands.WriteValueCommand().from_args(**write_value_args)
    bin_cmd = command.encoded_request

    # nesting flag was added
    assert bin_cmd[1:3] == bytearray([0xFF, 0x07])

    # assert symmetrical encoding / decoding
    decoded = command.request.parse(bin_cmd)
    assert decoded.object_id == write_value_args['object_id']
    assert decoded.data == write_value_args['data']


def test_command_from_decoded(write_value_args):
    cmd = commands.WriteValueCommand().from_decoded(write_value_args)

    assert cmd.encoded_request
    assert cmd.decoded_request == write_value_args

    assert cmd.encoded_response is None
    assert cmd.decoded_response is None


def test_command_from_encoded(write_value_args, write_value_resp, write_value_req):
    builder = commands.WriteValueCommand()
    encoded_request = builder.request.build(write_value_args)
    encoded_response = builder.response.build(write_value_resp)

    cmd = commands.WriteValueCommand().from_encoded(encoded_request, encoded_response)

    assert cmd.encoded_request == encoded_request
    assert cmd.encoded_response == encoded_response

    assert cmd.decoded_request == write_value_req
    assert cmd.decoded_response == write_value_resp


def test_command_props(write_value_args, write_value_resp, write_value_req):
    command = commands.WriteValueCommand()
    encoded_request = command.request.build(write_value_args)
    encoded_response = command.response.build(write_value_resp)

    # Request only
    for cmd in [
        command.from_encoded(request=encoded_request),
        command.from_decoded(request=write_value_req),
    ]:
        assert cmd.encoded_request == encoded_request
        assert cmd.decoded_request == write_value_req
        assert cmd.encoded_response is None
        assert cmd.decoded_response is None

    # Response only
    for cmd in [
        command.from_encoded(response=encoded_response),
        command.from_decoded(response=write_value_resp),
    ]:
        assert cmd.encoded_request is None
        assert cmd.decoded_request is None
        assert cmd.encoded_response == encoded_response
        assert cmd.decoded_response == write_value_resp


def test_pretty_raw():
    command = commands.WriteValueCommand()

    assert command._pretty_raw(bytes([0xde, 0xad])) == b'dead'
    assert command._pretty_raw(None) is None
