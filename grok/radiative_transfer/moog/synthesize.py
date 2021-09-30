
import os
import numpy as np
import subprocess
from collections import OrderedDict
from pkg_resources import resource_stream
from tempfile import mkdtemp

from grok.transitions import Transitions
from grok.radiative_transfer.moog.io import parse_summary_synth_output
from grok.radiative_transfer.utils import get_default_lambdas
from grok.utils import copy_or_write

def moog_synthesize(
        photosphere,
        transitions,
        lambdas=None,
        abundances=None,
        isotopes=None,
        terminal="x11",
        atmosphere_flag=0,
        molecules_flag=1,
        trudamp_flag=0,
        lines_flag=0,
        flux_int_flag=0,
        damping_flag=1,
        units_flag=0,
        scat_flag=1,
        opacit=0,
        opacity_contribution=2.0,
        verbose=False,
        dir=None,
        **kwargs
    ):
    
    if lambdas is not None:
        lambda_min, lambda_max, lambda_delta = lambdas
    else:
        lambda_min, lambda_max, lambda_delta = get_default_lambdas(transitions)

    N = 1 # number of syntheses to do
    
    _path = lambda basename: os.path.join(dir or "", basename)

    # Write photosphere and transitions.
    model_in, lines_in = (_path("model.in"), _path("lines.in"))
    copy_or_write(
        photosphere,
        model_in,
        format=kwargs.get("photosphere_format", "moog")
    )

    if isinstance(transitions, Transitions):
        # Cull transitions outside of the linelist, and sort. Otherwise MOOG dies.    
        mask = \
                (transitions["lambda"] >= (lambda_min - opacity_contribution)) \
            *   (transitions["lambda"] <= (lambda_max + opacity_contribution))
        use_transitions = transitions[mask]

        # dont use the table.sort function, because we might have read in air wavelengths
        # and have to calculate vacuum wavelengths first.
        indices = np.argsort(use_transitions["lambda"])
        use_transitions = use_transitions[indices]
    else:
        # You're living dangerously!
        use_transitions = transitions
        
    copy_or_write(
        use_transitions,
        lines_in,
        format=kwargs.get("transitions_format", "moog")
    )
    
    with resource_stream(__name__, "moog_synth.template") as fp:
        template = fp.read()
    
        if isinstance(template, bytes):
            template = template.decode("utf-8")

    kwds = dict(
        terminal=terminal,
        atmosphere_flag=atmosphere_flag,
        molecules_flag=molecules_flag,
        trudamp_flag=trudamp_flag,
        lines_flag=lines_flag,
        damping_flag=damping_flag,
        flux_int_flag=flux_int_flag,
        units_flag=units_flag,
        scat_flag=scat_flag,
        opacit=opacit,
        opacity_contribution=opacity_contribution,
        lambda_min=lambda_min,
        lambda_max=lambda_max,
        lambda_delta=lambda_delta
    )
    if verbose:
        kwds.update(dict(
            atmosphere_flag=2,
            molecules_flag=2,
            lines_flag=3
        ))

    # Abundances.
    if abundances is None:
        kwds["abundances_formatted"] = "0 1"
    else:
        raise NotImplementedError

    # Isotopes.
    if isotopes is None:
        kwds["isotopes_formatted"] = f"0 {N:.0f}"

    # I/O files:
    kwds.update(
        dict(
            standard_out="synth.std.out",
            summary_out="synth.sum.out",
            model_in=os.path.basename(model_in),
            lines_in=os.path.basename(lines_in)
        )
    )

    # Write the control file.
    contents = template.format(**kwds)
    control_path = _path("batch.par")
    with open(control_path, "w") as fp:
        fp.write(contents)

    # Execute MOOG(SILENT).
    process = subprocess.run(
        ["MOOGSILENT"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=os.path.dirname(control_path),
        input=os.path.basename(control_path) + "\n"*100,
        encoding="ascii"
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr)

    # Read the output.
    output = parse_summary_synth_output(_path(kwds["summary_out"]))
    wavelength, rectified_flux, meta = output[0]
    
    spectrum = OrderedDict([
        ("wavelength", wavelength),
        ("wavelength_unit", "Angstrom"),
        ("rectified_flux", rectified_flux),
    ])
    
    meta["dir"] = dir
    
    return (spectrum, meta)
    
