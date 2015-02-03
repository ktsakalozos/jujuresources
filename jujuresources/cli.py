import os
import sys
import socket
import argparse
from pkg_resources import iter_entry_points
from SimpleHTTPServer import SimpleHTTPRequestHandler
import SocketServer

from jujuresources import _fetch_resources
from jujuresources import _invalid_resources
from jujuresources import _load_resources


def arg(*args, **kwargs):
    """
    Decorator to add args to subcommands.
    """
    def _arg(f):
        if not hasattr(f, '_subcommand_args'):
            f._subcommand_args = []
        f._subcommand_args.append((args, kwargs))
        return f
    return _arg


def argset(name, *args, **kwargs):
    """
    Decorator to add sets of required mutually exclusive args to subcommands.
    """
    def _arg(f):
        if not hasattr(f, '_subcommand_argsets'):
            f._subcommand_argsets = {}
        f._subcommand_argsets.setdefault(name, []).append((args, kwargs))
        return f
    return _arg


def resources():
    """
    Juju CLI subcommand for dispatching resources subcommands.
    """
    eps = iter_entry_points('jujuresources.subcommands')
    ep_map = {ep.name: ep.load() for ep in eps}

    if '--description' in sys.argv:
        print 'Manage and mirror charm resources'
        return

    parser = argparse.ArgumentParser()
    subparsers = {}
    subparser_factory = parser.add_subparsers()
    subparsers['help'] = subparser_factory.add_parser('help', help='Display help for a subcommand')
    subparsers['help'].add_argument('command', nargs='?')
    subparsers['help'].set_defaults(subcommand='help')
    for name, subcommand in ep_map.iteritems():
        subparsers[name] = subparser_factory.add_parser(name, help=subcommand.__doc__)
        subparsers[name].set_defaults(subcommand=subcommand)
        for args, kwargs in getattr(subcommand, '_subcommand_args', []):
            subparsers[name].add_argument(*args, **kwargs)
        for argset in getattr(subcommand, '_subcommand_argsets', {}).values():
            group = subparsers[name].add_mutually_exclusive_group(required=True)
            for args, kwargs in argset:
                group.add_argument(*args, **kwargs)
    opts = parser.parse_args()
    if opts.subcommand == 'help':
        if opts.command:
            subparsers[opts.command].print_help()
        else:
            parser.print_help()
    else:
        sys.exit(opts.subcommand(opts) or 0)


@arg('-r', '--resources', default='resources.yaml',
     help='File or URL containing the YAML resource descriptions (default: ./resources.yaml)')
@arg('-d', '--output-dir', default='resources',
     help='Directory to place the fetched resources (default ./resources/)')
@arg('-u', '--base-url',
     help='Base URL from which to fetch the resources (if given, only the '
          'filename portion will be used from the resource descriptions)')
@arg('-a', '--all', action='store_true',
     help='Include all optional resources as well as required')
@arg('-q', '--quiet', action='store_true',
     help='Suppress output and only set the return code')
@arg('-f', '--force', action='store_true',
     help='Force re-download of valid resources')
def fetch(opts):
    """
    Create a local mirror of all resources (mandatory and optional) for a charm
    """
    resdefs = _load_resources(opts.resources, opts.output_dir)
    required_resources = resdefs['resources'].keys()
    all_resources = resdefs['all_resources'].keys()
    to_fetch = all_resources if opts.all else required_resources

    def reporthook(name, block, block_size, total_size):
        if name != reporthook.last_name:
            print 'Fetching {}...'.format(name)
            reporthook.last_name = name
    reporthook.last_name = None
    _fetch_resources(resdefs, to_fetch, opts.base_url, force=opts.force, reporthook=None if opts.quiet else reporthook)
    return verify(opts)


@arg('-r', '--resources', default='resources.yaml',
     help='File or URL containing the YAML resource descriptions (default: ./resources.yaml)')
@arg('-d', '--output-dir', default='resources',
     help='Directory containing the fetched resources (default ./resources/)')
@arg('-a', '--all', action='store_true',
     help='Include all optional resources as well as required')
@arg('-q', '--quiet', action='store_true',
     help='Suppress output and only set the return code')
def verify(opts):
    """
    Create a local mirror of all resources (mandatory and optional) for a charm
    """
    resdefs = _load_resources(opts.resources, opts.output_dir)
    required_resources = resdefs['resources'].keys()
    all_resources = resdefs['all_resources'].keys()
    to_fetch = all_resources if opts.all else required_resources

    invalid = _invalid_resources(resdefs, to_fetch)
    if not invalid:
        if not opts.quiet:
            print "All resources successfully downloaded"
        return 0
    else:
        if not opts.quiet:
            print "Invalid or missing resources: {}".format(', '.join(invalid))
        return 1


@arg('-d', '--output-dir', default='resources',
     help='Directory containing the fetched resources (default ./resources/)')
@arg('-H', '--host', default='',
     help='IP address on which to bind the mirror server')
@arg('-p', '--port', default=8080,
     help='Port on which to bind the mirror server')
def serve(opts):
    """
    Run a light-weight HTTP server hosting previously mirrored resources
    """
    if not os.path.exists(opts.output_dir):
        print "Resources dir '{}' not found.  Did you fetch?".format(opts.output_dir)
        return 1
    os.chdir(opts.output_dir)
    SocketServer.TCPServer.allow_reuse_address = True
    httpd = SocketServer.TCPServer(("", opts.port), SimpleHTTPRequestHandler)

    print "Serving at: http://{}:{}/".format(socket.gethostname(), opts.port)
    httpd.serve_forever()
