import re
import numpy as np
from astropy.io import registry
from astropy import units as u
from typing import OrderedDict

from grok.transitions import (Species, Transition, Transitions)
from grok.utils import safe_open

_strip_quotes = lambda s: s.strip("' ")
_strip_quotes_bytes = lambda s: _strip_quotes(s.decode("utf-8"))

# Alex Ji made this selection rule matrix. 12x12
# The rows are lower, going from 0-1 00 01 02 through 22 for llo1,llo2
# The cols are upper, going from 0-1 00 01 02 through 22 for lhi1,lhi2
# Index is 4*lo + hi+1
_all_level_map = np.array([
    [(0,0),(0,0),(0,1),(0,2), (0,1),(0,1),(0,1),(0,1), (0,2),(0,2),(0,1),(0,2)],
    [(0,0),(0,0),(0,1),(0,0), (0,1),(0,1),(0,1),(0,1), (0,2),(0,2),(0,1),(0,2)],
    [(1,0),(1,0),(0,1),(1,2), (0,1),(0,1),(0,1),(0,1), (0,2),(0,2),(0,1),(0,2)],
    [(2,0),(0,0),(0,1),(0,0), (0,1),(0,1),(0,1),(0,1), (0,2),(0,2),(0,1),(0,2)],
    
    [(1,0),(1,0),(1,0),(1,0), (1,1),(1,0),(1,1),(1,2), (1,2),(1,2),(1,2),(1,2)],
    [(1,0),(1,0),(1,0),(1,0), (0,1),(1,0),(0,1),(1,2), (1,2),(1,2),(1,2),(1,2)],
    [(1,0),(1,0),(1,0),(1,0), (1,1),(1,0),(1,1),(1,2), (1,2),(1,2),(1,2),(1,2)],
    [(1,0),(1,0),(1,0),(1,0), (2,1),(1,0),(2,1),(1,2), (1,2),(1,2),(1,2),(1,2)],

    [(2,0),(1,0),(2,1),(2,0), (2,1),(2,1),(2,1),(2,1), (2,2),(2,0),(2,1),(2,2)],
    [(2,0),(2,0),(2,1),(2,0), (2,1),(2,1),(2,1),(2,1), (0,2),(2,2),(2,1),(2,2)],
    [(1,0),(1,0),(2,1),(1,2), (2,1),(2,1),(2,1),(2,1), (1,2),(1,2),(2,1),(1,2)],
    [(2,0),(2,0),(2,1),(2,0), (2,1),(2,1),(2,1),(2,1), (2,2),(2,2),(2,1),(2,2)]
])


def parse_references(lines):
    reference_header = "References:"
    for i, line in enumerate(lines):
        if line.strip() == reference_header:
            break
    else:
        raise ValueError(f"No references header '{reference_header}' found.")

    delimiter = ". "
    references = OrderedDict([])
    for line in lines[i+1:]:
        if not line: 
            # blank line.
            continue
        number, *reference_text = line.split(delimiter)
        number = int(number.lstrip())
        references[number] = delimiter.join(reference_text).rstrip()
    return references


def as_species_with_correct_charge(representation):
    """
    Parse a Species object from a string representation in VALD.

    Note that VALD calls neutral Cu 'Cu 1', which is different to what
    we expect for the ground state, but we fix it here.
    """
    species = Species(_strip_quotes(representation))
    species.charge -= 1
    return species


def parse_levels(lower, upper):
    """
    Parse the level information encoded by VALD. An example might be:

    > parse_levels('LS 3d9.(2D).4d 3S', 'LS 3d8.(3P).4s.4p.(3P*) 1P*')
    """
    lower, upper = (lower.lstrip(), upper.lstrip())

    coupling_chars = 2
    all_levels = "spdfghik"
    unknown = ("X", "X")

    levels = []
    for level_description in (lower, upper):
        coupling = level_description[:coupling_chars]
        if coupling not in ("LS", "JJ", "JK", "LK"):
            return unknown
            
        # These Nones are in case we find no level information.
        level_descs = [None, None] + re.findall(f"[{all_levels}]", level_description[coupling_chars:]) 

        # We're just getting the last two levels.
        for level_desc in level_descs[::-1][:2]:
            if level_desc is None:
                levels.append(-1)
            else:
                levels.append(all_levels.index(level_desc))

    llo, llo2, lhi, lhi2 = levels
    # From https://github.com/alexji/turbopy/blob/main/turbopy/linelists.py:
    if llo >= 3 or lhi >= 3:
        llo, lhi = (2, 3)
    elif (llo < 0) & (lhi < 0):
        return unknown
    elif np.abs(lhi - llo) == 1:
        pass
    elif llo2 >= 3 or lhi2 >= 3:
        llo, lhi = (2, 3)
    else:
        ixrow = 4*llo + llo2+1
        ixcol = 4*lhi + lhi2+1
        llo, lhi = _all_level_map[ixrow, ixcol]
    
    return (all_levels[llo], all_levels[lhi])


def read_extract_stellar_long_output(path):
    """
    Read transitions that have been extracted from the Vienna Atomic Line Database
    version 3 (VALD3), using the "extract stellar" in long format.

    Documentation at https://www.astro.uu.se/valdwiki/select_output

    """

    path, content, content_stream = safe_open(path)
    lines = content.split("\n")
    
    header_pattern = "\s*(?P<lambda_start>[\d\.]+),\s*(?P<lambda_end>[\d\.]+),\s*(?P<n_selected>\d+),\s*(?P<n_processed>\d+),\s*(?P<v_micro>[\d\.]+), Wavelength region, lines selected, lines processed, Vmicro"

    meta = re.match(header_pattern, lines[0])
    if not meta:
        raise ValueError(f"Cannot match header with '{header_pattern}'")
    
    meta = meta.groupdict()
    for k in meta.keys():
        dtype = int if k.startswith("n_") else float
        meta[k] = dtype(meta[k])

    names = (
        "species",
        "lambda_air", 
        "E_lower",
        "v_micro",
        "log_gf", 
        "gamma_rad",
        "gamma_stark",
        "vdW",
        "lande_factor",
        "lande_depth",
        "reference"        
    )
    data = np.genfromtxt(
        path,
        skip_header=3,
        max_rows=meta["n_selected"],
        delimiter=",",
        dtype={
            "names": names,
            "formats": ("U10", float, float, float, float, float, float, float, float, float, "U100")
        },
        converters={
            0: _strip_quotes_bytes,
            10: _strip_quotes_bytes,
        }
    )

    # TODO: Go back and assign these references to individual lines?
    references = parse_references(lines)

    transitions = []
    for row in data:
        row_as_dict = dict(zip(names, row))
        row_as_dict["species"] = as_species_with_correct_charge(row_as_dict["species"])
        row_as_dict["lambda_air"] *= u.Angstrom
        row_as_dict["E_lower"] *= u.eV
        row_as_dict["gamma_rad"] *= (1/u.s)
        row_as_dict["gamma_stark"] *= (1/u.s)

        transitions.append(
            Transition(
                lambda_vacuum=None,
                **row_as_dict
            )
        )

    return Transitions(transitions)


def read_extract_all_or_extract_element(path):
    """
    Read transitions that have been extracted from the Vienna Atomic Line Database
    version 3 (VALD3), using the "extract all" or "extract element" formats.

    Documentation at https://www.astro.uu.se/valdwiki/presformat_output
    """

    path, content, content_stream = safe_open(path)
    lines = content.split("\n")

    header_rows = 2
    keys_and_dtypes = (
        ("species", as_species_with_correct_charge),
        ("lambda_air", lambda value: float(value) * u.Angstrom),
        ("log_gf", float),
        ("E_lower", lambda value: float(value) * u.eV), # chi_lower
        ("j_lower", float),
        ("E_upper", lambda value: float(value) * u.eV), # chi_upper
        ("j_upper", float),
        ("lande_factor_lower", float),
        ("lande_factor_upper", float),
        ("lande_factor_mean", float),
        ("gamma_rad", lambda value: float(value) * (1/u.s)),
        ("gamma_stark", lambda value: float(value) * (1/u.s)),
        ("vdW", float),
        ("lower_level_desc", str),
        ("upper_level_desc", str),
        ("reference", str),
    )
    data = {}
    transitions = []
    for i, line in enumerate(lines[header_rows:]):
        if line.strip() == "References:":
            break

        if i % 4 == 0:
            if line.count(",") < 10: 
                # Could be something like a footnote.
                break
            
            for (key, dtype), value in zip(keys_and_dtypes, line.split(",")):
                data[key] = dtype(value)

        elif i % 4 == 1:
            data["lower_level_desc"] = _strip_quotes(line)
        elif i % 4 == 2:
            data["upper_level_desc"] = _strip_quotes(line)
        elif i % 4 == 3:
            data["reference"] = _strip_quotes(line)

            # Parse the orbital information.
            lower_orbital_type, upper_orbital_type = parse_levels(data["lower_level_desc"], data["upper_level_desc"])
            data["lower_orbital_type"] = lower_orbital_type
            data["upper_orbital_type"] = upper_orbital_type

            # Now put it into a transition.
            transitions.append(
                Transition(
                    lambda_vacuum=None,
                    **data
                )
            )
            data = {}

    references = parse_references(lines[i+1:])

    # TODO: Assign the references back to the individual transitions?
    return Transitions(transitions)
    

def read_vald(path):
    """
    Read transitions exported from the Vienna Atomic Line Database
    version 3 (VALD3).
    
    Here we assume the format is not known, and we try our best.
    """
    
    methods = [
        read_extract_all_or_extract_element,
        read_extract_stellar_long_output,
    ]
    for method in methods:
        try:
            t = method(path)
        except:
            continue
        else:
            return t
    else:
        raise IOError(f"Unable to read VALD format. Tried methods: {methods}")
            

def identify_vald_all_or_extract_element(origin, *args, **kwargs):
    """
    Identify a line list being in VALD format from an 'extract all' or 'extract element'
    request.
    """
    if args[1] is None:
        return False

    first_line_pattern = ".+Lande factors\s+Damping parameters"
    # This assumes Angstroms and eV as the units. We could not be so fussy!
    second_line_pattern = "^Elm\s+Ion\s+WL_air\(A\)\s+log\(gf\)\s+E_low\(eV\)\s+J lo\s+E_up\(eV\)\s+J up\s+lower\s+upper\s+mean\s+Rad\.\s+Stark\s+Waals"
    first_line = args[1].readline()
    if isinstance(first_line, bytes):
        first_line = first_line.decode("utf-8")
    second_line = args[1].readline()
    if isinstance(second_line, bytes):
        second_line = second_line.decode("utf-8")
    
    # Reset pointer.
    args[1].seek(0)

    return (re.match(first_line_pattern, first_line) is not None 
        and re.match(second_line_pattern, second_line) is not None)
        

def identify_vald_stellar(origin, *args, **kwargs):
    """ Identify a line list being in VALD 'stellar' format. """
    if args[1] is None:
        return False

    zeroth_line_pattern = "^\s*[\d\.]+,\s*[\d\.]+,\s*\d+,\s\d+,\s[\d\.]+,\s*Wavelength region,\s*lines selected,\s*lines processed, Vmicro"
    zeroth_line = args[1].readline()
    if isinstance(zeroth_line, bytes):
        zeroth_line = zeroth_line.decode("utf-8")
    
    args[1].seek(0)
    return re.match(zeroth_line_pattern, zeroth_line) is not None

    


registry.register_reader("vald", Transitions, read_vald)
registry.register_reader("vald.stellar", Transitions, read_extract_stellar_long_output)
registry.register_identifier("vald", Transitions, identify_vald_all_or_extract_element)
registry.register_identifier("vald.stellar", Transitions, identify_vald_stellar)