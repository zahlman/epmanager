from functools import partial
from inspect import Parameter, signature as signature_of, _empty
from .parser import DefaultParser


_REGISTRY = {}


def _as_dict(decorator_spec):
    if isinstance(decorator_spec, str):
        return {'help': decorator_spec}
    elif isinstance(decorator_spec, dict):
        return decorator_spec.copy()
    else:
        raise TypeError(
            f'spec for parameter `{param_name}` must be either string or dict'
        )


def _add_to_parser(parser, param_name, decorator_spec, signature):
    decorator_spec = _as_dict(decorator_spec)
    add_method = parser.add_argument
    if param_name.startswith('_'):
        add_method, param_name = parser.add_option, param_name[1:]
    param_info = signature.parameters.get(param_name, None)
    param_spec = {}
    if param_info is None:
        add_method = parser.add_option
    else:
        if param_info.kind == Parameter.VAR_KEYWORD:
            add_method = parser.add_option
        if param_info.default is not _empty:
            param_spec['default'] = param_info.default
        annotation = param_info.annotation
        if callable(annotation) and annotation is not _empty:
            param_spec['type'] = annotation
    add_method(param_name, decorator_spec, param_spec)


def _setup_entrypoint(
    dispatch, parser_class, name, description, param_specs, func
):
    name = name or func.__name__
    if description is None: # but allow desc == ''
        description = func.__doc__.splitlines()[0] if func.__doc__ else ''
    parser = parser_class(
        dispatch, func, {'name': name, 'description': description}
    )
    for param_name, decorator_spec in param_specs.items():
        _add_to_parser(parser, param_name, decorator_spec, signature_of(func))
    func.invoke = parser.invoke
    # Make this info accessible later, for generating pyproject.toml content
    # and for testing purposes.
    func.entrypoint_name = name
    func.entrypoint_desc = description
    _REGISTRY[name] = f'{func.__module__}:{func.__name__}.invoke'
    return func


def default_dispatch(func, args):
    """Default invoker."""
    # Any errors that occur here should be treated as programming errors,
    # because they indicate that the interface created through the
    # entrypoint decorator is broken (does not reliably map to the underlying
    # function's parameters). So we use assertions.
    positional = []
    # `args` come from the wrapper function and are not externally accessible,
    # so there is no need to make a copy even though we delete keys.
    keywords = args
    has_kwargs_param = False
    explicit_keywords = {}
    for name, param in signature_of(func).parameters.items():
        assert not has_kwargs_param # just a sanity check.
        if param.kind == Parameter.VAR_KEYWORD:
            has_kwargs_param = True # this should be the last parameter.
            continue
        if name in keywords:
            arg = keywords[name]
            del keywords[name]
        else:
            assert param.default != _REQUIRED, \
            f'command-line args missing necessary value for `{name}`'
            arg = keyword.get(name, param.default)
        if param.kind == Parameter.VAR_POSITIONAL:
            try:
                iter(arg)
            except TypeError:
                assert False, \
                'command-line arg for VAR_POSITIONAL parameter must be iterable'
            positional.extend(arg)
        elif param.kind == Parameter.POSITIONAL_OR_KEYWORD:
            positional.append(arg)
        elif param.kind == Parameter.KEYWORD_ONLY:
            explicit_keywords[name] = arg
        else:
            # POSITIONAL_ONLY (C interface stuff) is disallowed for now.
            assert False, \
            f'`{param.kind!s}` parameter in function signature not allowed'
    if not has_kwargs_param:
        assert not keywords, 'extra unusable command-line arguments found'
    return func(*positional, **explicit_keywords, **keywords)


def entrypoint(
    *, parser_class=DefaultParser, dispatch=default_dispatch,
    name=None, description=None, params=None, **kwargs
):
    return partial(
        _setup_entrypoint, dispatch, parser_class,
        name, description, params or kwargs
    )
