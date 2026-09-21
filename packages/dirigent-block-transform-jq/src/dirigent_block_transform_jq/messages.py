"""Every refusal the jq engine makes, catalogued under the ``transform.jq`` prefix.

A jq refusal reaches an attempt as ``plugin.transform_failed``: the verb frame owns the
failure, and the engine's sentence rides on it as the ``detail`` param.
"""

from dirigent_common import Catalogue

JQ = Catalogue("transform.jq")

PROGRAM_REFUSED = JQ.define("program_refused", "{detail}")

NO_OUTPUT = JQ.define(
    "no_output",
    "the program produced no output, and a transform step has to produce one; "
    "a program that means 'possibly nothing' emits [] or null explicitly",
)

MAP_OUTPUT_COUNT = JQ.define(
    "map_output_count",
    "the program produced {produced} outputs, and a map replaces an element with "
    "exactly one; a program that drops elements is a filter.jq step, and one that "
    "changes how many there are is a transform.jq step",
)

FILTER_OUTPUT_COUNT = JQ.define(
    "filter_output_count",
    "the program produced {produced} outputs, and a filter answers one true or false "
    "per element; a program that reshapes an element is a map.jq or transform.jq step",
)

FILTER_ANSWER = JQ.define(
    "filter_answer",
    "the program answered {answer}, and a filter answers true or false; jq's "
    "truthiness is not applied, so a program meaning 'has readings' writes '.count > 0'",
)
