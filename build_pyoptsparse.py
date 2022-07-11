#!/usr/bin/env python
import argparse
import os
import re
import shutil
import sys
import subprocess
from pathlib import Path, PurePath
import tempfile
from colors import *
from shutil import which

# Default options that the user can change with command line switches
opts = {
    'prefix': str(Path(Path.home() / 'ipopt')),
    'linear_solver': 'mumps',
    'build_pyoptsparse': True,
    'intel_compiler_suite': False,
    'snopt_dir': None,
    'hsl_tar_file': None,
    'include_paropt': False,
    'keep_build_dir': False,
    'check_sanity': True,
    'conda_cmd': 'conda',
    'force_rebuild': False,
    'ignore_conda': False,
    'verbose': False,
    'compile_required': True, # Not set directly by the user, but determined from other options
    'uninstall_built': False,
    'uninstall_conda_pkgs': False
}

# Information about the host, status, and constants
sys_info = {
    'gcc_major_ver': -1,
    'line_color': 'white',
    'msg_color': 'gray',
    'gnu_sanity_check_done': False,
    'python_sanity_check_done': False,
    'compile_cores': int(os.cpu_count()/2),
}

# Where to find each package, which branch to use if obtained by git,
# and which include file to test to see if it's already installed
build_info = {
    'metis': {
        'branch': 'releases/2.0.0',
        'url': 'https://github.com/coin-or-tools/ThirdParty-Metis.git',
        'src_lib_glob': 'libcoinmetis*',
        'include_subdir': 'metis',
        'include_file': 'metis.h'
    },
    'mumps': {
        'branch': 'releases/3.0.2',
        'url': 'https://github.com/coin-or-tools/ThirdParty-Mumps.git',
        'src_lib_glob': 'libcoinmumps*',
        'include_subdir': 'mumps',
        'include_file': 'mumps_c_types.h'
    },
    'ipopt': {
        'branch': 'releases/3.14.7',
        'url': 'https://github.com/coin-or/Ipopt.git',
        'src_lib_glob': 'lib*ipopt*',
        'include_subdir': '.',
        'include_glob_list': ['Ip*.hpp', 'Sens*.hpp'],
        'include_file': 'IpoptConfig.h'
    },
    'pyoptsparse': {
        'branch': 'v2.8.3',
        'url': 'https://github.com/mdolab/pyoptsparse.git',
    },
    'hsl': {
        'branch': 'releases/2.2.1',
        'url': 'https://github.com/coin-or-tools/ThirdParty-HSL',
        'src_lib_glob': 'libcoinhsl*',
        'include_subdir': 'hsl',
        'include_file': 'CoinHslConfig.h'
    },
    'paropt': {
        'branch': 'v2.0.2',
        'url': 'https://github.com/smdogroup/paropt.git'
    }
}

def process_command_line():
    """ Validate command line arguments and update options, or print usage and exit. """
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description='''
    Download, configure, build, and/or install pyOptSparse with IPOPT support and
    dependencies. Temporary working directories are created, which are removed
    after installation unless -d is used.
            ''',
        epilog='''
    NOTES:
    When using HSL as the linear solver, the source code tar file can be obtained
    from http://www.hsl.rl.ac.uk/ipopt/
    If PARDISO is selected as the linear solver, the Intel compiler suite with MKL
    must be available.

    Examples:
    build_pyoptsparse.py
    build_pyoptsparse.py -l pardiso
    build_pyoptsparse.py -l hsl -n -t ../../coinhsl-archive-2014.01.17.tar.gz
    '''
    )
    parser.add_argument("-a", "--paropt",
                        help="Add ParOpt support. Default: no ParOpt",
                        action="store_true",
                        default=opts['include_paropt'])
    parser.add_argument("-b", "--branch",
                        help=f"pyOptSparse git branch. \
                        Default: {build_info['pyoptsparse']['branch']}",
                        default=build_info['pyoptsparse']['branch'])
    parser.add_argument("-c", "--conda-cmd",
                        help=f"Command to install packages with if conda is used. \
                            Default: {opts['conda_cmd']}",
                        default=opts['conda_cmd'])
    parser.add_argument("-d", "--no-delete",
                        help="Do not erase the build directories after completion.",
                        action="store_true",
                        default=opts['keep_build_dir'])
    parser.add_argument("-e", "--ignore-conda",
                        help="Build from source even if conda is found.",
                        action="store_true",
                        default=opts['ignore_conda'])
    parser.add_argument("-f", "--force-rebuild",
                        help="If building a package from source, \
                              rebuild even if it's found to be installed.",
                        action="store_true",
                        default=opts['force_rebuild'])
    parser.add_argument("-k", "--no-sanity-check",
                        help="Skip the sanity checks.",
                        action="store_true",
                        default=not opts['check_sanity'])
    parser.add_argument("-i", "--intel",
                        help="Use the Intel compiler suite instead of GNU.",
                        action="store_true",
                        default=opts['intel_compiler_suite'])
    parser.add_argument("-l", "--linear-solver",
                        help="Which linear solver to use with IPOPT. Default: mumps",
                        choices=['mumps', 'hsl', 'pardiso'],
                        default=opts['linear_solver'])
    parser.add_argument("-n", "--no-install",
                        help="Prepare, but do NOT build/install pyOptSparse itself. \
                              Default: install",
                        action="store_true",
                        default=not opts['build_pyoptsparse'])
    parser.add_argument("-p", "--prefix",
                        help=f"Where to install. Default: {opts['prefix']}",
                        default=opts['prefix'])
    parser.add_argument("-s", "--snopt-dir",
                        help="Include SNOPT from SNOPT-DIR. Default: no SNOPT",
                        default=opts['snopt_dir'])
    parser.add_argument("-t", "--hsl-tar-file",
                        help="If HSL is the linear solver, use this as the path \
                        to the tar file of the HSL source. \
                        E.g. -t ../../coinhsl-archive-2014.01.17.tar.gz",
                        default=opts['hsl_tar_file'])
    parser.add_argument("--uninstall-built",
                        help="Attempt to remove an installation previously \
                              built from source using the same --prefix. \
                              Default: Do not uninstall",
                        action="store_true",
                        default=opts['uninstall_built'])
    parser.add_argument("--uninstall-conda-pkgs",
                        help="Attempt to remove packages metis, mumps, ipopt, \
                        and pyoptsparse installed previously by conda in the same env. \
                        Default: Do not uninstall",
                        action="store_true",
                        default=opts['uninstall_conda_pkgs'])
    parser.add_argument("-v", "--verbose",
                        help="Show output from git, configure, make, etc.",
                        action="store_true",
                        default=opts['verbose'])

    args = parser.parse_args()

    # Update options with user selections
    opts['include_paropt'] = args.paropt
    build_info['pyoptsparse']['branch'] = args.branch
    opts['conda_cmd'] = args.conda_cmd
    opts['keep_build_dir'] = args.no_delete
    opts['ignore_conda'] = args.ignore_conda
    opts['force_rebuild'] = args.force_rebuild
    opts['check_sanity'] = not args.no_sanity_check
    opts['linear_solver'] = args.linear_solver
    if opts['linear_solver'] == 'pardiso':
        opts['intel_compiler_suite'] = True
    else:
        opts['intel_compiler_suite'] = args.intel

    opts['prefix'] = args.prefix
    opts['build_pyoptsparse'] = not args.no_install
    opts['snopt_dir'] = args.snopt_dir
    opts['hsl_tar_file'] = args.hsl_tar_file
    opts['uninstall_built'] = args.uninstall_built
    opts['uninstall_conda_pkgs'] = args.uninstall_conda_pkgs
    opts['verbose'] = args.verbose

def announce(msg):
    """ Print an important message in color with a line above and below. """
    print("%s\n%s\n%s" %(LINE, color(msg, sys_info['msg_color']), LINE))

def note(msg):
    """
    Print a quick status message. If not in verbose mode, do not terminate with
    a newline because the result of the operation will print after.

    Parameters
    ----------
    msg : str
        The information to be printed.
    """
    if opts['verbose'] is False:
        print(msg, end="... ")
        sys.stdout.flush()
    else:
        print(msg + '...')

def note_ok():
    """ Print a green OK message to follow up a note() with. """
    if opts['verbose'] is False:
        print(green('OK'))

def initialize():
    """ Perform a collection of setup tasks """
    global dir_stack
    dir_stack = []

    if conda_is_active():
        opts['prefix']=os.environ['CONDA_PREFIX']
    elif venv_is_active():
        opts['prefix']=os.environ['VIRTUAL_ENV']

    global LINE
    LINE = color('=' * 78, fg=sys_info['line_color'])

def conda_is_active() -> bool:
    """ Determine if a conda environment is active. """
    return ('CONDA_PREFIX' in os.environ)

def allow_install_with_conda() -> bool:
    """ Determine if we can install with conda. """
    return conda_is_active() and not opts['ignore_conda']

def venv_is_active() -> bool:
    """ Determine if a Python virtual environment is active. """
    return ('VIRTUAL_ENV' in os.environ)

def run_cmd(cmd_list):
    """
    Run a command with provided arguments. Hide output unless there's an error
    or verbose mode is enabled.

    Parameters
    ----------
    cmd_list : list
        Each token of the command line is a separate member of the list.
    """
    if opts['verbose'] is False:
        subprocess.run(cmd_list, check=True, capture_output=True)
    else:
        subprocess.run(cmd_list, check=True)

def make_install(parallel_procs:int=sys_info['compile_cores'], make_args = None, do_install=True):
    """
    Run 'make' followed by 'make install' in the current directory.

    Parameters
    ----------
    parallel_procs : int
        Start this many parallel make processes. Defaults to half of the system cores.
        Some packages fail when built in parallel, so 1 should be used in those cases.
    """
    note('Building')
    os.environ['MAKEFLAGS'] = f'-j {str(parallel_procs)}'
    make_cmd=['make']
    if make_args is not None:
        make_cmd.extend(make_args)
    run_cmd(cmd_list=make_cmd)
    note_ok()

    if do_install is True:
        note('Installing')
        run_cmd(cmd_list=['make','install'])
        note_ok()

def run_conda_cmd(cmd_args):
    """
    Shorthand for performing a conda operation. 

    Parameters
    ----------
    cmd_list : list
        Each token of the command line is a separate member of the list. The conda
        executable name is prepended, so should not be included in the list.
    """
    cmd_list = [opts['conda_cmd']]
    cmd_list.extend(cmd_args)
    run_cmd(cmd_list)

def pip_install(pip_install_args):
    """
    Shorthand for performing a 'pip install' operation. 

    Parameters
    ----------
    pip_install_args : list
        Each token of the command line is a separate member of the list. The
        is prepended with 'python -m pip install'; '-q' is added when not verbose.
    """
    cmd_list = ['python', '-m', 'pip', 'install']
    if opts['verbose'] is False:
        cmd_list.append('-q')
    cmd_list.extend(pip_install_args)
    note('Installing packages with pip')
    run_cmd(cmd_list)
    note_ok()

def install_conda_pkg(pkg_name:str):
    """
    Shorthand for performing a 'conda install' operation for a single package. 

    Parameters
    ----------
    pkg_name : str
        The name of the package to install.
    """
    note(f'Installing {pkg_name.upper()} with conda')
    install_args = ['install', '-y', pkg_name]
    run_conda_cmd(cmd_args=install_args)
    note_ok()

def pushd(dirname):
    """
    Preserve the current directory name in a stack, then change to the specified directory.

    Parameters
    ----------
    dirname : str
        The absolute or relative name of the folder to change to.
    """
    dir_stack.append(str(Path.cwd()))
    os.chdir(dirname)
    print(f'Changed directory to {str(blue(Path.cwd()))}')

def popd():
    """ Change to the top directory name on the stack of names. """
    dirname = dir_stack.pop()
    os.chdir(dirname)
    print(f'Changed directory back to {blue(dirname)}')

def get_coin_inc_dir()->str:
    """
    Determine what the path to the MUMPS/METIS/IPOPT include directory is, if it exists.

    Returns
    -------
    str
        The absolute path to the correct existing directory, or None if not found.
    """
    coin_inc_dirs = ['coin-or', 'coin']
    for coin_dir in coin_inc_dirs:
        coin_path = Path(opts["prefix"]) / 'include' / coin_dir
        if coin_path.is_dir():
            return str(coin_path)

    return None

def get_coin_lib_name(pkg:str)->str:
    """
    Determine whether the required lib starts with 'lib' or 'libcoin'.

    Parameters
    ----------
    pkg : str
        The name of the library to test.

    Returns
    -------
    str
        The pkg parameter prefaced with either 'coin' or nothing.
    """
    lib_vars = ['coin', '']

    for lv in lib_vars:
        lib_glob = f"lib{lv}{pkg}*"
        found_libs = sorted(Path(f"{opts['prefix']}/lib").glob(lib_glob))
        if len(found_libs) > 0:
            return f'{lv}{pkg}'

    return None

def git_clone(build_key:str):
    """
    Create a temporary directory, change to it, and clone the repository associated
    with the specified package key.

    Parameters
    ----------
    build_key : str
        A key in the build_info dict with info about the selected package.

    Returns
    -------
    context manager OR str
        When the 'keep_build_dir' option is False, an object with info about the directory,
        which causes the directory to be cleaned up and removed when it goes out of scope.
        When the 'keep_build_dir' option is True, returns a str with the name of the folder.
    """
    d = build_info[build_key]
    announce(f'Building {build_key.upper()} from source code')
    if opts['keep_build_dir'] is True:
        build_dir = tempfile.mkdtemp()
        dir_name = build_dir
        print(f"Remember to delete {blue(dir_name)} afterwards.")
    else:
        build_dir = tempfile.TemporaryDirectory()
        dir_name = build_dir.name

    note(f'Cloning {d["url"]}')
    run_cmd(cmd_list=['git', 'clone', '-q', d['url'], dir_name])
    note_ok()
    pushd(dir_name)

    # We don't care about the "detached HEAD" warning:
    run_cmd(cmd_list=['git', 'config', '--local', 'advice.detachedHead', 'false'])
    run_cmd(cmd_list=['git', 'checkout', '-q', d['branch']])
    return build_dir

def allow_build(build_key:str) -> bool:
    """
    Determine whether the specified package should be installed with conda or built from source.

    Parameters
    ----------
    build_key : str
        A key in the build_info dict with info about the selected package.

    Returns
    -------
    bool
        True if the package should be built, false if installed by conda.    
    """
    coin_dir = get_coin_inc_dir()
    if coin_dir is None:
        build_ok = True
    else:
        d = build_info[build_key]
        include_file = Path(coin_dir) / d['include_subdir'] / d['include_file']
        build_ok = opts['force_rebuild'] or not include_file.is_file()

    if build_ok is False:
        print(f"{build_key.upper()} is already installed under {opts['prefix']}, {yellow('skipping build')}.")

    return build_ok

def install_metis_from_src():
    """ Git clone the METIS repo, build the library, and install it and the include files. """
    if not allow_build('metis'):
        return

    build_dir = git_clone('metis')
    run_cmd(['./get.Metis'])
    os.environ['CFLAGS'] = '-Wno-implicit-function-declaration'
    note("Running configure")
    run_cmd(cmd_list=['./configure', f'--prefix={opts["prefix"]}'])
    note_ok()
    make_install()
    popd()

def install_metis():
    """ Install METIS either through conda or building. """
    if allow_install_with_conda():
        install_conda_pkg('metis')
    else:
        install_metis_from_src()

def install_mumps_from_src():
    """ Git clone the MUMPS repo, build the library, and install it and the include files. """
    if not allow_build('mumps'):
        return

    build_dir = git_clone('mumps')
    run_cmd(['./get.Mumps'])
    coin_dir = get_coin_inc_dir()
    cflags = f'-w -I{opts["prefix"]}/include -I{coin_dir} -I{coin_dir}/metis'
    fcflags = cflags
    if sys_info['gcc_major_ver'] >= 10:
        fcflags = '-fallow-argument-mismatch ' + fcflags

    metis_lib = get_coin_lib_name('metis')
    config_opts = [
        '--with-metis',
        f'--with-metis-lflags=-L{opts["prefix"]}/lib -l{metis_lib}',
        f'--with-metis-cflags={cflags}',
        f'--prefix={opts["prefix"]}',
        f'CFLAGS={cflags}',
        f'FCFLAGS={fcflags}'
    ]
    cnf_cmd_list = ['./configure']
    cnf_cmd_list.extend(config_opts)

    note("Running configure")
    run_cmd(cmd_list=cnf_cmd_list)
    note_ok()
    make_install(1) # MUMPS build can fail with parallel make
    popd()

def install_paropt_from_src():
    """
    Git clone the PAROPT repo, build the library, and install it and the include files.
    """
    build_dir = git_clone('paropt')

    # Use build defaults as per ParOpt instructions:
    Path('Makefile.in.info').rename('Makefile.in')
    make_install(make_args=[f'PAROPT_DIR={Path.cwd()}'], do_install=False)
    note('Installing with pip')
    run_cmd(cmd_list=['python','-m','pip','install','./'])
    popd()

def install_ipopt_from_src(config_opts:list):
    """
    Git clone the IPOPT repo, build the library, and install it and the include files.

    Parameters
    ----------
    config_opts : list
        Additional options to use with the IPOPT configure script.
    """
    if not allow_build('ipopt'):
        return

    build_dir = git_clone('ipopt')
    cnf_cmd_list = ['./configure', f'--prefix={opts["prefix"]}', '--disable-java']
    cnf_cmd_list.extend(config_opts)
    note("Running configure")
    run_cmd(cmd_list=cnf_cmd_list)
    note_ok()
    make_install()
    popd()

def install_with_mumps():
    """ Install METIS, MUMPS, and IPOPT. """
    install_metis()
    if allow_install_with_conda():
        install_conda_pkg('mumps')
        install_conda_pkg('ipopt')
    else:
        install_mumps_from_src()
        coin_dir = get_coin_inc_dir()

        mumps_lib = get_coin_lib_name('mumps')
        ipopt_opts = [
            '--with-mumps',
            f'--with-mumps-lflags=-L{opts["prefix"]}/lib -l{mumps_lib}',
            f'--with-mumps-cflags=-I{coin_dir}/mumps',
            '--without-asl',
            '--without-hsl'
        ]
        install_ipopt_from_src(config_opts=ipopt_opts)

def install_hsl_from_src():
    """ Build HSL from the user-supplied source tar file. """
    if not allow_build('hsl'):
        return

    build_dir = git_clone('hsl')

    # Extract the HSL tar file and rename the folder to 'coinhsl'
    # First, determine the name of the top-level folder:
    tar = subprocess.run(['tar', 'vtf', opts['hsl_tar_file']], encoding='UTF-8',
          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    first_line = tar.stdout.splitlines()[0]
    hsl_dir_name = first_line.split()[8].replace('/','')
    run_cmd(cmd_list=['tar', 'xf', opts['hsl_tar_file']]) # Extract
    Path(hsl_dir_name).rename('coinhsl') # Rename

    coin_dir = get_coin_inc_dir()
    metis_lib = get_coin_lib_name('metis')
    cnf_cmd_list = [
        './configure',
        f'--prefix={opts["prefix"]}',
        '--with-metis',
        f'--with-metis-lflags=-L{opts["prefix"]}/lib -l{metis_lib}',
        f'--with-mumps-cflags=-I{coin_dir}',
    ]

    note("Running configure")
    run_cmd(cmd_list=cnf_cmd_list)
    note_ok()
    make_install()
    popd()

def install_with_hsl():
    """ Install pyOptSparse using the HSL linear solver """
    install_metis()
    install_hsl_from_src()

    coin_dir = get_coin_inc_dir()
    metis_lib = get_coin_lib_name('metis')
    ipopt_opts = [
        '--with-hsl',
        f'--with-hsl-lflags=-L{opts["prefix"]}/lib -lcoinhsl -l{metis_lib}',
        f'--with-hsl-cflags=-I{coin_dir}/hsl',
        '--disable-linear-solver-loader'
    ]
    install_ipopt_from_src(config_opts=ipopt_opts)
    install_pyoptsparse_from_src()

def install_with_pardiso():
    """ Build IPOPT with the PARDISO linear solver. """
    # install_ipopt_from_src(config_opts=['--with-lapack=-mkl'])
    install_ipopt_from_src(config_opts=['--with-pardiso'])

    # pyOptSparse doesn't do well with Intel compilers, so unset:
    # select_gnu_compiler()

    install_pyoptsparse_from_src()

def copy_snopt_files(build_dirname):
    """
    Copy SNOPT source files into the pyOptSparse build dir, excluding snopth.f.

    Parameters
    ----------
    build_dirname : str
        The directory where pyOptSparse is being built/installed from.
    """
    note('Copying SNOPT source files')
    snoptc_f_list = sorted(Path(opts['snopt_dir']).rglob('snoptc.f'))
    all_snopt_files = sorted(Path(snoptc_f_list[0]).parent.glob('*'))

    dest_dir = str(Path(build_dirname) / 'pyoptsparse' / 'pySNOPT' / 'source')
    
    exclude_snopth_f = re.compile('.*snopth.f')
    for sfile in all_snopt_files:
        src_file = str(sfile)
        if not exclude_snopth_f.match(src_file):
            shutil.copy2(src_file, dest_dir)

    note_ok()

def install_pyoptsparse_from_src():
    """ Git clone the pyOptSparse repo and use pip to install it. """
    pip_install(pip_install_args=['numpy','sqlitedict'])
    build_dir = git_clone('pyoptsparse')

    os.environ['IPOPT_INC'] = get_coin_inc_dir()
    os.environ['IPOPT_LIB'] = f'{opts["prefix"]}/lib'
    os.environ['CFLAGS'] = '-Wno-implicit-function-declaration -std=c99'

    # Build PAROPT if selected:
    if opts['include_paropt'] is True:
        install_paropt_from_src()

    # Pull in SNOPT source:
    if opts['snopt_dir'] is not None:
        build_dir_str = build_dir if isinstance(build_dir, str) else build_dir.name
        copy_snopt_files(build_dir_str)

    if opts['build_pyoptsparse'] is True:
        pip_install(pip_install_args=['--no-cache-dir', './'])
    else:
        print(f"""
{LINE}
{yellow('Not')} building pyOptSparse by request. Make sure to set
these environment variables before building it yourself:

export IPOPT_INC={opts["prefix"]}/include/coin-or
export IPOPT_LIB={opts["prefix"]}/lib
{LINE}
        """)

    popd()

def install_pyoptsparse():
    """ Install pyOptSparse either with conda or by building it. """
    if allow_install_with_conda() and opts['snopt_dir'] is None:
        install_conda_pkg('pyoptsparse')
    else:
        install_pyoptsparse_from_src()

def uninstall_built_item(build_key:str):
    """ Uninstall a specific item that was previously built from source code. """
    d = build_info[build_key]
    inc_dir = Path(opts['prefix']) / 'include' / 'coin-or' / d['include_subdir']


    if 'include_glob_list' in d:
    # If there's a list of glob patterns, remove found files individually instead
    # of removing an entire include subdirectory:
        for glob_item in d['include_glob_list']:
            for inc_file in sorted(Path(inc_dir / glob_item)):
                Path(inc_file).unlink()

        try:
            inc_dir.rmdir()
        except:
            pass
    else:
    # If there's no chance that other include files will be installed in the same
    # folder, just remove the whole subdirectory.
        if inc_dir.is_dir():
            note(f'Removing {build_key.upper()} include directory')
            shutil.rmtree(inc_dir)
            note_ok()

    # Remove individual library files.
    lib_dir = Path(opts['prefix']) / 'lib'
    lib_file_list = sorted(lib_dir.glob(d['src_lib_glob']))
    if len(lib_file_list) > 0:
        note('Removing {build_key.upper()} library files')
        for lib_file in lib_file_list:
            Path(lib_file).unlink()
        note_ok()    

def uninstall_paropt_and_pyoptsparse():
    """ Both ParOpt and pyOptSparse were installed with pip. """
    # Uninstall pyOptSparse
    try:
        import pyoptsparse
        note('Removing pyOptSparse')
        run_cmd(cmd_list=['pip','uninstall','-y','pyOptSparse'])
        note_ok()
    except ImportError:
        pass   

    # PAROPT
    try:
        import paropt
        note('Removing PAROPT')
        run_cmd(cmd_list=['pip','uninstall','-y','paropt'])
        note_ok()
    except ImportError:
        pass

def uninstall_built():
    """ Attempt to remove files that were previously installed when building from source. """
    uninstall_paropt_and_pyoptsparse()

    for build_key in ['ipopt', 'hsl', 'mumps', 'metis']:
        uninstall_built_item(build_key)

def check_compiler_sanity():
    """ Build and run programs written in C, C++, and FORTRAN to test the compilers. """
    build_dir = tempfile.TemporaryDirectory()
    pushd(build_dir.name)

    note(f'Testing {os.environ["CC"]}')
    with open('hello.c', 'w', encoding="utf-8") as f:
        f.write('#include <stdio.h>\nint main() {\nprintf("cc works!\\n");\nreturn 0;\n}\n')

    run_cmd(cmd_list=[os.environ['CC'], '-o', 'hello_c', 'hello.c'])
    run_cmd(cmd_list=['./hello_c'])
    note_ok()

    note(f'Testing {os.environ["CXX"]}')
    with open('hello.cc', 'w', encoding="utf-8") as f:
        f.write('#include <iostream>\nint main() {\nstd::cout << "c++ works!" << std::endl;\nreturn 0;\n}\n')

    run_cmd(cmd_list=[os.environ['CXX'], '-o', 'hello_cxx', 'hello.cc'])
    run_cmd(cmd_list=['./hello_cxx'])
    note_ok()

    note(f'Testing {os.environ["FC"]}')
    with open('hello.f90', 'w', encoding="utf-8") as f:
        f.write("program hello\n  print *, 'fortran works!'\nend program hello")

    run_cmd(cmd_list=[os.environ['FC'], '-o', 'hello_f', 'hello.f90'])
    run_cmd(cmd_list=['./hello_f'])
    note_ok()

    popd()

def check_sanity():
    """ Determine if all the required commands are there and can build if necessary. """
    announce("Testing build environment functionality. Can be skipped with -k.")

    errors = []
    required_cmds = []

    if opts['compile_required'] is True:
        required_cmds.extend(['make', 'git', os.environ['CC'], os.environ['CXX'], os.environ['FC']])
        if opts['build_pyoptsparse'] is True:
            required_cmds.extend(['pip', 'swig'])
    else:
        required_cmds.append(opts['conda_cmd'])

    if opts['hsl_tar_file'] is not None:
        required_cmds.append('tar')
        if not Path(opts['hsl_tar_file']).is_file():
            errors.append(f"{red('ERROR')}: HSL tar file {yellow(opts['hsl_tar_file'])} does not exist.")

    if opts['include_paropt'] is True:
        required_cmds.append('mpicxx')

    if opts['snopt_dir'] is not None:
        if not Path(opts['snopt_dir']).is_dir():
            errors.append(f"{red('ERROR')}: SNOPT folder {yellow(opts['snopt_dir'])} does not exist.")

    for cmd in required_cmds:
        cmd_path = which(cmd)
        if cmd_path is None:
            errors.append(f"{red('ERROR')}: Required command {yellow(cmd)} not found.")
        elif opts['verbose'] is True:
            print(f"{green('FOUND')}: {cmd} is {cmd_path}")

    if len(errors) > 0:
        for err in errors:
            print(err)

        exit(1)

    if opts['compile_required'] is True:
        check_compiler_sanity()

def select_intel_compilers():
    """ Set environment variables to use Intel compilers. """
    os.environ['CC'] = 'icc'
    os.environ['CXX'] = 'icpc'
    os.environ['FC'] = 'ifort'
    sys_info['gcc_major_ver'] = -1

def select_gnu_compilers():
    """ Set environment variables to use GNU compilers. """
    os.environ['CC'] = 'gcc'
    os.environ['CXX'] = 'g++'
    os.environ['FC'] = 'gfortran'
    gcc_ver = subprocess.run(['gcc', '-dumpversion'], capture_output=True)
    sys_info['gcc_major_ver'] = int(gcc_ver.stdout.decode('UTF-8').split('.')[0])    

def finish_setup():
    """ Finalize settings based on provided options and environment state. """
    if opts['intel_compiler_suite'] is True:
        select_intel_compilers()
    else:
        select_gnu_compilers()

    # Determine whether any compiling will actually be performed
    opts['compile_required'] = not (allow_install_with_conda() and opts['snopt_dir'] is None and
                opts['include_paropt'] is False and opts['hsl_tar_file'] is None)

    # Change snopt_dir to an absolute path
    if opts['snopt_dir'] is not None:
        opts['snopt_dir'] = str(Path(opts['snopt_dir']).resolve())

    if opts['hsl_tar_file'] is not None:
        opts['hsl_tar_file'] = str(Path(opts['hsl_tar_file']).resolve())

    if opts['check_sanity']:
        check_sanity()

def perform_install():
    """ Initiate all the required actions in the script. """
    initialize()
    process_command_line()

    early_exit = False
    if opts['uninstall_built']:
        uninstall_built()
        early_exit = True

    if opts['uninstall_conda_pkgs']:
        pass
        early_exit = True

    if early_exit is True:
        exit(0)

    finish_setup()

    if opts['linear_solver'] == 'mumps':
        install_with_mumps()
        install_pyoptsparse()
    elif opts['linear_solver'] == 'pardiso':
        install_with_pardiso()
    elif opts['linear_solver'] == 'hsl':
        install_with_hsl()

