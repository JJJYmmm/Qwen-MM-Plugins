"""Docstrings are a single prose source for the actual MCP schema and website export."""

import inspect
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, Field, ValidationError, field_validator

import mcp_framework as fw


class Args(BaseModel):
    text: str
    repeat: int = Field(default=1, ge=1, le=10)
    explicit: str = Field(default="ok", description="Explicit field documentation")

    @field_validator("text")
    @classmethod
    def nonempty(cls, value):
        if not value:
            raise ValueError("empty text")
        return value


def documented(arguments):
    """Repeat some text.

    Useful for testing descriptions. 中文也可以。

    Args:
        text (str): Text to repeat.
            Continued field documentation.
        repeat (int): Number of repetitions.
        explicit: This must not override Field(description=...).

    Returns:
        Text content blocks. Not included in the public tool description.
    """
    return [{"type": "text", "text": arguments["text"]}]


def spec(handle=documented, **metadata):
    return fw._spec_from_module(SimpleNamespace(TOOL={"name": "repeat", "args": Args, **metadata}, handle=handle))


def test_google_docstring_supplies_tool_and_parameter_descriptions():
    tool = spec()
    assert tool.description == "Repeat some text.\n\nUseful for testing descriptions. 中文也可以。"
    fields = tool.meta["inputSchema"]["properties"]
    assert fields["text"]["description"] == "Text to repeat.\nContinued field documentation."
    assert fields["repeat"]["description"] == "Number of repetitions."
    assert fields["explicit"]["description"] == "Explicit field documentation"
    assert "Returns:" not in tool.description and "Args:" not in tool.description


def test_defaults_constraints_requiredness_and_validators_survive():
    tool = spec()
    fields = tool.input_schema["properties"]
    assert tool.input_schema["required"] == ["text"]
    assert fields["repeat"]["default"] == 1
    assert fields["repeat"]["minimum"] == 1 and fields["repeat"]["maximum"] == 10
    assert tool.args_model(text="hello").repeat == 1
    for bad in ({"text": "hello", "repeat": 11}, {"text": ""}, {"repeat": 2}):
        with pytest.raises(ValidationError):
            tool.args_model(**bad)


def test_shared_model_is_not_mutated_and_wrapper_receives_the_same_descriptions():
    tool = spec()
    assert Args.model_fields["text"].description is None
    assert tool.args_model is not Args
    wrapper = fw._make_wrapper(tool)
    field = inspect.signature(wrapper).parameters["text"].annotation.__metadata__[0]
    assert field.description == tool.input_schema["properties"]["text"]["description"]


@pytest.mark.parametrize("description", ["Explicit description", ""])
def test_explicit_description_keeps_legacy_behavior(description):
    tool = spec(description=description)
    assert tool.description == description
    assert tool.args_model is Args
    assert tool.input_schema == fw.tool_schema(Args)


def test_missing_docstring_requires_an_explicit_description():
    with pytest.raises(ValueError, match="provide TOOL.description"):
        spec(lambda arguments: [])


def test_plain_docstring_can_contain_legacy_parameters_prose():
    def handler(arguments):
        """A description.\n\nParameters:\nArbitrary prose, not structured Args."""
        return []

    assert spec(handler).description == inspect.getdoc(handler)


def test_explicit_plain_format_preserves_examples_and_args_as_public_prose():
    tool = spec(docstring_format="plain")
    assert tool.description == inspect.getdoc(documented)
    assert tool.args_model is Args


def test_unknown_docstring_format_is_rejected():
    with pytest.raises(ValueError, match="docstring_format"):
        spec(docstring_format="typo")


@pytest.mark.asyncio
async def test_fastmcp_advertises_docstring_field_descriptions():
    from mcp.server.fastmcp import FastMCP

    tool = spec()
    server = FastMCP("test-docstrings")
    server.add_tool(fw._make_wrapper(tool), name=tool.name, description=tool.description, structured_output=False)
    wire = (await server.list_tools())[0]
    assert wire.description == tool.description
    assert (
        wire.inputSchema["properties"]["text"]["description"] == tool.input_schema["properties"]["text"]["description"]
    )


@pytest.mark.parametrize("args", ["        typo: Wrong name.", "        text: First.\n        text: Duplicate."])
def test_unknown_and_duplicate_args_fail_at_registration(args):
    def handler(arguments):
        return []

    handler.__doc__ = "Summary.\n\n    Args:\n" + args
    with pytest.raises(ValueError, match="docstring argument"):
        spec(handler)


def test_example_migrates_without_changing_its_public_schema():
    from qwen_mm_plugins_example.tools import echo

    tool = fw._spec_from_module(echo)
    assert tool.description == "Echo a message back as text. Demonstrates a text-only tool."
    assert tool.input_schema["properties"]["repeat"]["description"] == "How many times to repeat the message (1-10)."
    assert tool.handle({"message": "hello", "repeat": 2}) == [{"type": "text", "text": "hello\nhello"}]
