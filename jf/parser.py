"""JF query parser"""
import parser
import re
import logging

logger = logging.getLogger(__name__)


def filter_tree(node):
    """Filter interesting nodes from a parse tree"""
    if node[0] < 200:
        return [node[1]]
    subtrees = [filter_tree(subnode) for subnode in node[1:]]
    if len(subtrees) == 1:
        return subtrees[0]
    return subtrees


def flatten(tree):
    """Flatten tree"""
    logger.debug("flatten '%s'", tree)
    if maxdepth(tree) > 1:
        ret = []
        for node in tree:
            ret.extend(flatten(node))
        return ret
    return tree


def merge_not(arr, char=','):
    """Merge items until character is detected before yielding them."""
    logger.debug(arr)
    merged = ''
    for val in arr:
        if val != char:
            if merged:
                merged += ' '
            merged += val
        else:
            yield merged
            merged = ''
    if merged:
        yield merged


def merge_lambdas(arr):
    """Merge jf lambdas to mappers and filters"""
    ret = 'lambda x, *rest: ('
    rest = False
    first = True
    for val, keep in arr:
        if not keep and not rest:
            ret += '), arr'
            rest = True
        if not first:
            ret += ', '
        ret += val
        first = False
    if first:
        ret += 'arr'
    elif not rest:
        ret += '), arr'
    return ret


kwargre = re.compile(r'[^!><=]+=[^><=]+')


def tag_keywords(val):
    """Tag keywords"""
    return (val, kwargre.match(val) is None)


def join_tokens(arr):
    """Join tokens if joined tokens contain the same instructions"""
    logger.debug("join_tokens '%s'", arr)
    ret = ''
    for tok in arr:
        if not ret:
            ret += tok
        elif ret[-1] not in '(){}[],.:"\'' and tok[0] not in '(){}[],.:"\'':
            ret = ret + ' ' + tok
        else:
            ret += tok

    return ret


def maxdepth(tree):
    """Calculate tree depth"""
    if isinstance(tree, list):
        return 1 + max([maxdepth(node) for node in tree])
    return 0


def make_param_list(part):
    """Make a parameter list from tokens"""
    logger.debug("make_param_list %s", part)
    if len(part) == 1 and isinstance(part[0], str):
        return part

    while maxdepth(part) < 4:
        part = [part]
    return list(merge_not([join_tokens(flatten(x)) for x in part]))


def parse_part(function):
    """Parse a part of pipeline definition"""
    ret = 'lambda arr: '
    arr_set = False
    for part in function:
        logger.debug(part)
        if part[0][0] == '(':
            paramlist = ['']
            if len(part) == 3:
                paramlist = make_param_list(part[1])
            logger.debug("paramlist '%s'", paramlist)
            params = [tag_keywords(x) for x in paramlist]
            if not arr_set:
                lambda_params = merge_lambdas(params)
            else:
                lambda_params = " ".join([x[0] for x in params])
            ret += "(" + lambda_params + ')'
            arr_set = True
        elif isinstance(part[0], list):
            ret += "".join([x[0] for x in part])
        else:
            ret += "".join(part)
        logger.debug("Part: %s -> %s", part, ret)
    return ret


def ast_parser(query):
    """TODO: make a full feature ast parser"""
    import ast
    nodes = ast.parse(query).node.body[0].value.elts
    filters = [ast.dump(elt) for elt in nodes]
    # moduleargs = lambda function: function.func.value.args
    # functionargs = lambda function: function.args
    # code[f3.func.value.args[0].col_offset:]
    return filters


def simpleparser(query, igen='igen'):
    """Simple regex parser"""
    import regex
    functionre = r'([a-zA-Z][^() ,]+)'
    argsre = r'\(([^,()]*)([^()]*(\((?2)?[^()]*\)[^()]*)*)\)'
    classfunction = r'(\.[^ ]*)?'
    lambdare_str = r'%s%s%s' % (functionre, argsre, classfunction)
    logger.debug(lambdare_str)
    lambdasub = r'lambda arr: \1(lambda x: (\2)\3, %s=arr)\5' % igen
    lambdare = regex.compile(lambdare_str)
    query = lambdare.sub(lambdasub, query)
    logger.debug("After Lambdare: %s", query)
    return query


def reparser(query):
    """Complex regex parser"""
    import regex
    res = {
        "functionre": r'([a-zA-Z][^()]+)',
        "argsre": r'(\([^()=]*(\(([^()]*(?3)?[^()]*)*\))?)',
        "kwargsre": r'(, [^()]+)?',
        "classfunction": r'(\.[^ ]*)?',
    }
    lambdare_str = r'%s%s%s\)%s' % (res["functionre"], res["argsre"],
                                    res["kwargsre"], res["classfunction"])
    lambdasub = r'lambda arr: \1(lambda x, *rest: \2), arr\5)\6'
    lambdare = regex.compile(lambdare_str)
#    query = lambdare.sub(r'lambda arr: \1(lambda x, *rest: \2, arr)\4', query)
    query = lambdare.sub(lambdasub, query)
    logger.debug("After Lambdare: %s", query)
    return query


def guess_query_type(m):
    for val in flatten(m):
        if val in ('==', '>', '<', '!=', '>=', '<='):
            return 'filter'
    return 'map'


def parse_query(string):
    """Parse query string and convert it to a evaluatable pipeline argument"""
    logger.debug("Parsing: %s", string)
    query_tree = filter_tree(parser.expr("%s," % string).tolist())[0]
    ret = ''
    for func in query_tree:
        logger.debug("Function definition length: %d", len(func))
        if maxdepth(func) < 3:
            logger.debug("Shallow: %s", func)
            ret += func[0]
            continue
        if func[0][0] == '{':
            logger.debug("Detected short syntax. Guessing.")
            func = [['map'], [['(']] + [func] + [[')']]]
        if func[0][0] == '(':
            logger.debug("Detected short syntax. Guessing.")
            func = [['filter'], func]
        logger.debug("Parsing parts: %s", func)
        if len(func) == 2:
            part = parse_part(func)
            ret += part
        elif len(func) == 3:
            func = [[func[0][0] + "".join([x[0] for x in func[1]])], func[2]]
            logger.debug(repr(func))
            part = parse_part(func)
            ret += part
        elif len(func) > 3:
            part = parse_part(func)
            ret += part
        else:
            ret += func[0]
        logger.debug("ret: %s", ret)
    return ret