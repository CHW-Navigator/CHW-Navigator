from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from .clinical_vocabulary import reject_clinical_derivation
from .diagnostics import Diagnostic, DiagnosticCode
from .special_functions import (
    GESTATIONAL_AGE_FUNCTION_VERSION,
    GESTATIONAL_AGE_REFERENCE_VERSION,
    SPECIAL_FUNCTION_STATUSES,
    sha256_text,
    validate_status_coverage,
)


CHT_CONF_TEST_HARNESS_VERSION = "5.0.4"
CHT_CONF_VERSION = "6.4.1"


@dataclass(frozen=True, slots=True)
class ReviewedCHTProfile:
    cht_version: str
    profile_id: str
    extension_lib_xpath: bool
    extension_lib_expression: bool
    harness_version: str = CHT_CONF_TEST_HARNESS_VERSION
    harness_core_version: str = "4.11"
    cht_conf_version: str = CHT_CONF_VERSION


REVIEWED_CHT_PROFILES = {
    "4.22.0": ReviewedCHTProfile(
        cht_version="4.22.0",
        profile_id="cht-core-4.22",
        extension_lib_xpath=True,
        extension_lib_expression=False,
    ),
    "5.2.0": ReviewedCHTProfile(
        cht_version="5.2.0",
        profile_id="cht-core-5.2",
        extension_lib_xpath=True,
        extension_lib_expression=True,
    ),
}


@dataclass(frozen=True, slots=True)
class GeneratedCHTFile:
    path: str
    content: str
    sha256: str


@dataclass(frozen=True, slots=True)
class CHTSpecialFunctionBundle:
    profile: ReviewedCHTProfile
    files: tuple[GeneratedCHTFile, ...]
    diagnostics: tuple[Diagnostic, ...]


class UnreviewedCHTVersionError(ValueError):
    code = DiagnosticCode.UNREVIEWED_CHT_VERSION


def reviewed_cht_profile(version: str) -> ReviewedCHTProfile:
    profile = REVIEWED_CHT_PROFILES.get(version)
    if profile is None:
        raise UnreviewedCHTVersionError(
            f"{DiagnosticCode.UNREVIEWED_CHT_VERSION}: CHT version '{version}' has no reviewed lowering profile."
        )
    return profile


def reviewed_cht_versions() -> tuple[str, ...]:
    return tuple(sorted(REVIEWED_CHT_PROFILES))


def gestational_age_extension_source() -> str:
    return f'''\
'use strict';

const FUNCTION_VERSION = "{GESTATIONAL_AGE_FUNCTION_VERSION}";
const REFERENCE_DATA_VERSION = "{GESTATIONAL_AGE_REFERENCE_VERSION}";
const DAY_MS = 86400000;
const ESTIMATED_PREGNANCY_DAYS = 280;
const MAX_SUPPORTED_ELAPSED_DAYS = 315;

const response = (status, value = '') => ({{ t: 'str', v: `${{status}}|${{value}}` }});
const readValue = value => {{
  if (!value || typeof value !== 'object') return undefined;
  const raw = value.t === 'arr' ? value.v && value.v[0] : value.v;
  if (raw && typeof raw === 'object' && 'textContent' in raw) return raw.textContent;
  return raw;
}};
const parseDate = value => {{
  if (typeof value !== 'string' || !/^\\d{{4}}-\\d{{2}}-\\d{{2}}$/.test(value)) return undefined;
  const timestamp = Date.parse(`${{value}}T00:00:00.000Z`);
  return Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 10) === value ? timestamp : undefined;
}};
const roundHalfEven = (value, digits) => {{
  const factor = 10 ** digits;
  const scaled = value * factor;
  const floor = Math.floor(scaled);
  const fraction = scaled - floor;
  if (Math.abs(fraction - 0.5) < Number.EPSILON * Math.max(1, Math.abs(scaled))) return (floor % 2 === 0 ? floor : floor + 1) / factor;
  return Math.round(scaled) / factor;
}};

module.exports = function(operationEnvelope, lmpEnvelope, asOfEnvelope) {{
  try {{
    const operation = readValue(operationEnvelope);
    if (operation === 'versions') return {{ t: 'str', v: `${{FUNCTION_VERSION}}|${{REFERENCE_DATA_VERSION}}` }};
    if (operation !== 'compute') return response('input_invalid');
    if (!FUNCTION_VERSION || !REFERENCE_DATA_VERSION) return response('reference_data_unavailable');
    const lmpValue = readValue(lmpEnvelope);
    const asOfValue = readValue(asOfEnvelope);
    if (!lmpValue || !asOfValue) return response('input_missing');
    const lmp = parseDate(lmpValue);
    const asOf = parseDate(asOfValue);
    if (lmp === undefined || asOf === undefined) return response('input_invalid');
    const elapsedDays = (asOf - lmp) / DAY_MS;
    if (elapsedDays < 0 || elapsedDays > MAX_SUPPORTED_ELAPSED_DAYS) return response('outside_supported_domain');
    const weeks = roundHalfEven(elapsedDays / 7, 1);
    const edd = new Date(lmp + ESTIMATED_PREGNANCY_DAYS * DAY_MS).toISOString().slice(0, 10);
    if (!Number.isFinite(weeks) || !edd) return response('numeric_failure');
    return response('ok', `${{weeks}},${{edd}}`);
  }} catch (_error) {{
    return response('execution_failure');
  }}
}};
'''


def _status_groups(path: str) -> str:
    return "\n".join(
        f'<group relevant="{path} = &apos;{status}&apos;"><note><label>Technical computation status: {status}</label></note></group>'
        for status in SPECIAL_FUNCTION_STATUSES
    )


def gestational_age_xform() -> str:
    status = "/data/technical/pregnancy/lmp_calculation/status"
    groups = _status_groups(status)
    return f'''\
<?xml version="1.0" encoding="UTF-8"?>
<h:html xmlns:h="http://www.w3.org/1999/xhtml" xmlns="http://www.w3.org/2002/xforms" xmlns:jr="http://openrosa.org/javarosa" xmlns:cht="https://communityhealthtoolkit.org">
<h:head>
<h:title>Technical gestational-age calculation</h:title>
<model>
<instance><data id="technical_gestational_age"><meta><instanceID/></meta><inputs><as_of_date></as_of_date><lmp_date></lmp_date></inputs><technical><pregnancy><lmp_calculation><estimated_delivery_date></estimated_delivery_date><gestational_age_weeks></gestational_age_weeks><guarded_payload></guarded_payload><raw_result></raw_result><raw_versions></raw_versions><status></status><value_payload></value_payload><version_match></version_match></lmp_calculation></pregnancy></technical></data></instance>
<instance id="contact-summary"/>
<bind nodeset="/data/meta/instanceID" type="string" jr:preload="uid" readonly="true()"/>
<bind nodeset="/data/technical/pregnancy/lmp_calculation/raw_versions" type="string" calculate="cht:extension-lib(&apos;gestational-age-from-lmp.js&apos;, &apos;versions&apos;)"/>
<bind nodeset="/data/technical/pregnancy/lmp_calculation/version_match" type="boolean" calculate="/data/technical/pregnancy/lmp_calculation/raw_versions = &apos;{GESTATIONAL_AGE_FUNCTION_VERSION}|{GESTATIONAL_AGE_REFERENCE_VERSION}&apos;"/>
<bind nodeset="/data/technical/pregnancy/lmp_calculation/raw_result" type="string" calculate="cht:extension-lib(&apos;gestational-age-from-lmp.js&apos;, &apos;compute&apos;, /data/inputs/lmp_date, /data/inputs/as_of_date)"/>
<bind nodeset="/data/technical/pregnancy/lmp_calculation/guarded_payload" type="string" calculate="if(/data/technical/pregnancy/lmp_calculation/version_match, /data/technical/pregnancy/lmp_calculation/raw_result, &apos;version_mismatch|&apos;)"/>
<bind nodeset="{status}" type="string" calculate="substring-before(/data/technical/pregnancy/lmp_calculation/guarded_payload, &apos;|&apos;)"/>
<bind nodeset="/data/technical/pregnancy/lmp_calculation/value_payload" type="string" calculate="substring-after(/data/technical/pregnancy/lmp_calculation/guarded_payload, &apos;|&apos;)"/>
<bind nodeset="/data/technical/pregnancy/lmp_calculation/gestational_age_weeks" type="decimal" calculate="if({status} = &apos;ok&apos;, number(substring-before(/data/technical/pregnancy/lmp_calculation/value_payload, &apos;,&apos;)), &apos;&apos;)"/>
<bind nodeset="/data/technical/pregnancy/lmp_calculation/estimated_delivery_date" type="date" calculate="if({status} = &apos;ok&apos;, substring-after(/data/technical/pregnancy/lmp_calculation/value_payload, &apos;,&apos;), &apos;&apos;)"/>
</model>
</h:head>
<h:body>
<input ref="/data/inputs/lmp_date"><label>Last menstrual period date</label></input>
<input ref="/data/inputs/as_of_date"><label>Evaluation date</label></input>
{groups}
</h:body>
</h:html>
'''


def wfa_xform() -> str:
    status = "/data/technical/anthropometry/weight_for_age_z_score_status"
    groups = _status_groups(status)
    return f'''\
<?xml version="1.0" encoding="UTF-8"?>
<h:html xmlns:h="http://www.w3.org/1999/xhtml" xmlns="http://www.w3.org/2002/xforms" xmlns:jr="http://openrosa.org/javarosa" xmlns:cht="https://communityhealthtoolkit.org">
<h:head>
<h:title>Technical weight-for-age Z-score</h:title>
<model>
<instance><data id="technical_wfa_z_score"><meta><instanceID/></meta><inputs><age_months></age_months><sex></sex><weight_kg></weight_kg></inputs><technical><anthropometry><weight_for_age_z_score></weight_for_age_z_score><weight_for_age_z_score_status></weight_for_age_z_score_status></anthropometry></technical></data></instance>
<instance id="contact-summary"/>
<bind nodeset="/data/meta/instanceID" type="string" jr:preload="uid" readonly="true()"/>
<bind nodeset="/data/technical/anthropometry/weight_for_age_z_score" type="decimal" calculate="z-score(&apos;weight-for-age&apos;, /data/inputs/sex, /data/inputs/age_months, /data/inputs/weight_kg)"/>
<bind nodeset="{status}" type="string" calculate="if(string-length(string(/data/technical/anthropometry/weight_for_age_z_score)) &gt; 0, &apos;ok&apos;, &apos;numeric_failure&apos;)"/>
</model>
</h:head>
<h:body>
<input ref="/data/inputs/sex"><label>Reference-table sex</label></input>
<input ref="/data/inputs/age_months"><label>Completed months</label></input>
<input ref="/data/inputs/weight_kg"><label>Weight in kilograms</label></input>
{groups}
</h:body>
</h:html>
'''


def lower_reviewed_special_functions(target_cht_version: str) -> CHTSpecialFunctionBundle:
    profile = reviewed_cht_profile(target_cht_version)
    extension = gestational_age_extension_source()
    gestational_form = gestational_age_xform()
    wfa_form = wfa_xform()
    reject_clinical_derivation({"source": extension}, context="generated CHT extension library")
    diagnostics = [
        Diagnostic(
            DiagnosticCode.NATIVE_REFERENCE_DATA_UNVERIFIED,
            "warning",
            "Native CHT z-score() uses deployment-controlled chart data whose version is not verified by this compiler.",
            "forms/app/technical_wfa_z_score.xml",
        ),
        *validate_status_coverage(gestational_form),
        *validate_status_coverage(wfa_form),
    ]
    values = {
        "extension-libs/gestational-age-from-lmp.js": extension,
        "forms/app/technical_gestational_age.xml": gestational_form,
        "forms/app/technical_wfa_z_score.xml": wfa_form,
    }
    files = tuple(
        GeneratedCHTFile(path=path, content=content, sha256=sha256_text(content))
        for path, content in sorted(values.items())
    )
    return CHTSpecialFunctionBundle(profile=profile, files=files, diagnostics=tuple(diagnostics))


def write_cht_special_function_bundle(
    bundle: CHTSpecialFunctionBundle,
    output_dir: str | Path,
) -> tuple[Path, ...]:
    target = Path(output_dir).resolve()
    written: list[Path] = []
    for artifact in bundle.files:
        destination = (target / artifact.path).resolve()
        destination.relative_to(target)
        if destination.exists():
            existing = destination.read_text(encoding="utf-8")
            if existing != artifact.content:
                raise FileExistsError(f"refusing to overwrite divergent unmanaged file: {artifact.path}")
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(artifact.content, encoding="utf-8")
        written.append(destination)
    manifest_path = target / "special-function-manifest.json"
    manifest = {
        "schema_version": "1.0.0",
        "target_profile": {
            "cht_version": bundle.profile.cht_version,
            "profile_id": bundle.profile.profile_id,
            "cht_conf_version": bundle.profile.cht_conf_version,
            "harness_version": bundle.profile.harness_version,
            "harness_core_version": bundle.profile.harness_core_version,
            "extension_lib_xpath": bundle.profile.extension_lib_xpath,
            "extension_lib_expression": bundle.profile.extension_lib_expression,
        },
        "files": [
            {"path": artifact.path, "sha256": artifact.sha256}
            for artifact in bundle.files
        ],
        "diagnostics": [
            {
                "code": diagnostic.code,
                "severity": diagnostic.severity,
                "message": diagnostic.message,
                **({"path": diagnostic.path} if diagnostic.path is not None else {}),
            }
            for diagnostic in bundle.diagnostics
        ],
    }
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if manifest_path.exists() and manifest_path.read_text(encoding="utf-8") != manifest_text:
        raise FileExistsError("refusing to overwrite divergent unmanaged file: special-function-manifest.json")
    if not manifest_path.exists():
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(manifest_text, encoding="utf-8")
        written.append(manifest_path)
    return tuple(written)


def attachment_sha256(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()
