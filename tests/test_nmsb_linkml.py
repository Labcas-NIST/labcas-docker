import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import yaml
from openpyxl import Workbook


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "airflow" / "scripts" / "parsers"))

import nmsb_linkml  # noqa: E402


class NMSBLinkMLParserTests(unittest.TestCase):
    def _write_workbook(self, path: Path, rows) -> None:
        workbook = Workbook()
        worksheet = workbook.active
        for row in rows:
            worksheet.append(row)
        workbook.save(path)

    def test_normalizes_synthetic_fields_and_omits_open_decisions(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            collection_path = tmp / "nmsb_collection.xlsx"
            dataset_path = tmp / "example_dataset.xlsx"
            self._write_workbook(
                collection_path,
                [
                    ["collection", "values"],
                    ["collection_name", "NMSB Collection"],
                    ["collection_description", "Synthetic collection used by a unit test"],
                    ["principal_contact_name", "Example Contact"],
                    ["data_category", "Characterization"],
                    ["core_capabilities", "Microbial Measurements"],
                    ["primary_focus_areas", "Microbiome"],
                    [
                        "participating_NIST_division",
                        "Biosystems and Biomaterials Division, Division 644",
                    ],
                    ["owner_principal", "all_NIST"],
                ],
            )
            self._write_workbook(
                dataset_path,
                [
                    ["dataset", "values"],
                    ["dataset_title", "Example organism NIST0001"],
                    ["dataset_description", "Synthetic NMSB entry NIST0001"],
                    ["assay_technique", "cell_culture"],
                    ["starting_material_type", "cells"],
                    ["data_capture_start_date", datetime(2026, 4, 30)],
                    ["dataset_ID", None],
                    ["workflow_id", "NA"],
                ],
            )

            collection = nmsb_linkml.read_key_value_workbook(collection_path)
            dataset = nmsb_linkml.read_key_value_workbook(dataset_path)
            elab = {
                "resolved_fields": {
                    "material_supplier_institution": "Example Institute",
                    "material_lot_code": "LOT-001",
                    "restriction_on_usage": "Example restriction",
                    "liquid_media_name": "Example liquid medium",
                    "solid_media_name": "Example solid medium",
                },
                "excluded_unresolved_fields": {"type_strain": "not confirmed"},
                "source_files": ["synthetic-source"],
            }
            payload, report = nmsb_linkml.normalize_nmsb(
                collection,
                dataset,
                elab,
                nist_id="NIST0000",
                dataset_id="NMSBCollection/NIST0000",
            )

            self.assertEqual(payload["dataset_title"], "Example organism NIST0000")
            self.assertEqual(payload["dataset_ID"], "NMSBCollection/NIST0000")
            self.assertEqual(payload["material_reference_code"], "NIST0000")
            self.assertEqual(payload["NIST_ID"], "NIST0000")
            self.assertEqual(
                payload["elabs_resource_title"], "Example Institute_NIST0000_LOT-001"
            )
            self.assertEqual(payload["restriction_on_usage"], "Example restriction")
            self.assertEqual(payload["liquid_media_name"], "Example liquid medium")
            self.assertEqual(payload["solid_media_name"], "Example solid medium")
            self.assertNotIn("identification_methods", payload)
            self.assertNotIn("type_strain", payload)
            self.assertNotIn("workflow_id", payload)
            self.assertIn("type_strain", report["excluded_unresolved_fields"])

            output = tmp / "nmsb.yaml"
            report_path = tmp / "report.json"
            nmsb_linkml.write_outputs(payload, report, output, report_path)
            self.assertEqual(yaml.safe_load(output.read_text()), payload)


if __name__ == "__main__":
    unittest.main()
