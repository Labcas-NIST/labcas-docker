import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "airflow" / "scripts" / "parsers"))

import cell_provenance  # noqa: E402


PRIVATE_FIXTURES_AVAILABLE = (
    (ROOT / "data" / "raw" / "CellExpansion-04092026_Bundle").is_dir()
    and (ROOT / "data" / "raw" / "conf" / "CellLineCrossWalk.xlsx").is_file()
)


@unittest.skipUnless(
    PRIVATE_FIXTURES_AVAILABLE,
    "Private runtime fixtures are not included; provide them to run these parser integration tests.",
)
class CellProvenanceParserTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.bundle_dir = ROOT / "data" / "raw" / "CellExpansion-04092026_Bundle"
        self.workbook = ROOT / "data" / "raw" / "conf" / "CellLineCrossWalk.xlsx"

    def _load_components(self):
        bundle = cell_provenance.discover_bundle_layout(self.bundle_dir)
        components = cell_provenance.load_components(bundle)
        return bundle, components

    def _generate(self, tmp_root: Path):
        return cell_provenance.generate(
            bundle_dir=self.bundle_dir,
            workbook_path=self.workbook,
            output_dir=tmp_root / "metadata",
            staging_dir=tmp_root / "staging",
            archive_root=tmp_root / "archive",
            collection="cell_expansion_collection",
        )

    def test_load_mapping_model_reads_expected_slots_and_activity_union(self) -> None:
        model = cell_provenance.load_mapping_model(self.workbook)

        self.assertIn("InputConnector", model.schema_fields)
        self.assertEqual(model.schema_fields["InputConnector"].target_slot, "input_connector")
        self.assertIn("collection_name", model.collection_slots)
        self.assertIn("dataset_title", model.dataset_slots)
        self.assertIn("file_name", model.file_slots)

        self.assertEqual(
            model.activity_source_fields,
            [
                "ActivityBaseType",
                "ActivityDateTime",
                "CellCompositeName",
                "CellShortName",
                "CellUniqueID",
                "CultureContainerReplicateCode",
                "CultureContainerReplicateMultiplier",
                "CultureContainerReplicateNumber",
                "DataList",
                "DeltaTime",
                "InputConnector",
                "OutputConnector",
                "PassageNumber",
                "PreviousCultureContainerReplicateCode",
                "PreviousDateTime",
                "UnitOperationInstance",
                "UnitOperationInstanceStep",
            ],
        )
        self.assertIn("CellShortName", model.activity_source_fields)
        self.assertNotIn("InputConnector", model.entity_source_fields)

    def test_component_metadata_normalizes_keys_but_preserves_values(self) -> None:
        _, components = self._load_components()
        mapping = cell_provenance.load_mapping_model(self.workbook)
        monitor = next(
            component for component in components if component.component_name == "CellExpansion-000-2_Monitor"
        )

        metadata = cell_provenance._component_metadata(monitor, mapping)

        self.assertIn("input_connector", metadata)
        self.assertIn("step", metadata)
        self.assertEqual(
            metadata["output_connector"],
            "ASE-9211-AAVS1-50bp-del-HOM-rack0b0-r3cE_CellExpansion-000_p2_20251030T101520Z_rep1-2_Monitor-P2DT1H",
        )
        self.assertIn("raw_source_metadata", metadata)
        self.assertIn('"DataList"', json.dumps(metadata["raw_source_metadata"]))

    def test_reference_publish_sources_associate_real_files_to_monitor_step(self) -> None:
        bundle, components = self._load_components()
        sources, missing = cell_provenance._reference_publish_sources(bundle, components)

        self.assertEqual(missing, [])
        self.assertEqual(len(sources), 2)

        first = sources[0]
        self.assertEqual(first.artifact_role, "data")
        self.assertEqual(first.primary_component.component_name, "CellExpansion-000-2_Monitor")
        self.assertEqual(
            [component.component_name for component in first.related_components],
            [
                "CellExpansion-000-2_Monitor",
                "ASE-9211-AAVS1-50bp-del-HOM-rack0b0-r3cE_CellExpansion-000_p2_20251030T101520Z_rep1-2_Monitor-P2DT1H",
            ],
        )
        self.assertEqual(
            first.source_rel_path,
            "CellExpansion-000_DataList/50 bp del., 60' after plating in dish 11012026f r1.tif",
        )

    def test_dataset_version_defaults_to_v1_for_new_bundle_shape(self) -> None:
        bundle, components = self._load_components()
        self.assertEqual(cell_provenance._dataset_version(bundle), "1")
        self.assertEqual(cell_provenance._bundle_instance_id(bundle, components), "CellExpansion-000")

    def test_build_aggregate_bundle_payload_returns_selected_components(self) -> None:
        _, components = self._load_components()
        selected = [
            component
            for component in components
            if component.component_name in {"CellExpansion-000-2_Monitor", "CellExpansion-000-4_End"}
        ]

        payload = cell_provenance.build_aggregate_bundle_payload(selected)

        self.assertEqual(len(payload), 2)
        self.assertEqual(
            {item["ComponentName"] for item in payload},
            {"CellExpansion-000-2_Monitor", "CellExpansion-000-4_End"},
        )

    def test_generate_writes_cfgs_manifests_packages_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            result = self._generate(tmp_root)

            self.assertEqual(
                result["dataset_id"], "cell_expansion_collection/CellExpansion-000_v1"
            )
            self.assertEqual(result["file_count"], 13)

            report = json.loads((tmp_root / "staging" / "ingestion_report.json").read_text())
            self.assertEqual(report["component_count"], 10)
            self.assertEqual(report["publishable_file_count"], 13)
            self.assertEqual(report["resolved_reference_file_count"], 2)
            self.assertEqual(report["missing_referenced_file_count"], 0)
            self.assertEqual(report["missing_referenced_files"], [])
            self.assertEqual(report["fields_outside_activity_allowlist"], [])
            self.assertEqual(report["entity_only_preserved_fields"], [])
            self.assertEqual(report["unmapped_source_fields"], [])
            self.assertEqual(
                report["unused_mapping_rows"],
                ["ActivityBaseType", "PreviousCultureContainerReplicateCode"],
            )
            self.assertEqual(report["synthetic_component_bundle_count"], 10)
            self.assertEqual(len(report["missing_required_values"]), 13)

            dataset_cfg = (
                tmp_root
                / "metadata"
                / "cell_expansion_collection"
                / "CellExpansion-000_v1"
                / "CellExpansion-000_v1.cfg"
            ).read_text()
            self.assertIn(
                "input_connector=ASE9211-AAVS1-50bp-del-HOM_11/30/2023_p1_rack0b0-r3cE",
                dataset_cfg,
            )
            self.assertIn(
                "output_connector=ASE-9211-AAVS1-50bp-del-HOM-rack0b0-r3cE_CellExpansion-000_p2_20251030T101520Z_rep1-2_End-P3DT4H",
                dataset_cfg,
            )
            self.assertIn("activity_source_allowlist=", dataset_cfg)

            full_bundle_name = "unit_operation_instance-CellExpansion-000__bundle-full.json"
            monitor_bundle_name = (
                "unit_operation_instance-CellExpansion-000__step-2__component_type-Activity"
                "__component_name-CellExpansion-000-2_Monitor.json"
            )

            monitor_cfg = (
                tmp_root
                / "metadata"
                / "cell_expansion_collection"
                / "CellExpansion-000_v1"
                / f"{monitor_bundle_name}.cfg"
            ).read_text()
            self.assertIn("artifact_role=component_bundle", monitor_cfg)
            self.assertIn("download_bundle_type=sub_bundle", monitor_cfg)
            self.assertIn(f"FileName={monitor_bundle_name}", monitor_cfg)
            self.assertIn("step=2", monitor_cfg)
            self.assertIn(
                "data_list=[\"CellExpansion-000_DataList/50 bp del., 60' after plating in dish 11012026f r1.tif\", \"CellExpansion-000_DataList/50 bp del., 60' after plating in dish 11012026f r2.tif\"]",
                monitor_cfg,
            )
            self.assertIn(
                "output_connector=ASE-9211-AAVS1-50bp-del-HOM-rack0b0-r3cE_CellExpansion-000_p2_20251030T101520Z_rep1-2_Monitor-P2DT1H",
                monitor_cfg,
            )

            tif_cfg = (
                tmp_root
                / "metadata"
                / "cell_expansion_collection"
                / "CellExpansion-000_v1"
                / "50 bp del., 60' after plating in dish 11012026f r1.tif.cfg"
            ).read_text()
            self.assertIn(
                "SourceRelativePath=CellExpansion-000_DataList/50 bp del., 60' after plating in dish 11012026f r1.tif",
                tif_cfg,
            )
            self.assertIn("download_bundle_type=data", tif_cfg)
            self.assertIn(
                "related_component_names=CellExpansion-000-2_Monitor|ASE-9211-AAVS1-50bp-del-HOM-rack0b0-r3cE_CellExpansion-000_p2_20251030T101520Z_rep1-2_Monitor-P2DT1H",
                tif_cfg,
            )

            manifest = json.loads(
                (
                    tmp_root
                    / "metadata"
                    / "cell_expansion_collection"
                    / "cell_expansion_collection.manifest.json"
                ).read_text()
            )
            self.assertEqual(len(manifest["datasets"]), 1)
            self.assertEqual(manifest["datasets"][0]["id"], result["dataset_id"])
            self.assertEqual(len(manifest["files"]), 13)
            self.assertIn("packages", manifest)
            self.assertEqual(
                manifest["packages"]["dataset_packages"]["bundle"]["bundle_file_ids"],
                [f"cell_expansion_collection/CellExpansion-000_v1/{full_bundle_name}"],
            )

            packages = json.loads((tmp_root / "staging" / "download_packages.json").read_text())
            self.assertEqual(
                packages["dataset_packages"]["everything"]["everything_file_ids"],
                [
                    "cell_expansion_collection/CellExpansion-000_v1/50 bp del., 60' after plating in dish 11012026f r1.tif",
                    "cell_expansion_collection/CellExpansion-000_v1/50 bp del., 60' after plating in dish 11012026f r2.tif",
                    f"cell_expansion_collection/CellExpansion-000_v1/{full_bundle_name}",
                ],
            )
            monitor_package = next(
                package
                for package in packages["component_packages"]
                if package["component_name"] == "CellExpansion-000-2_Monitor"
            )
            self.assertEqual(
                monitor_package["bundle_file_ids"],
                [f"cell_expansion_collection/CellExpansion-000_v1/{monitor_bundle_name}"],
            )
            self.assertEqual(len(monitor_package["data_file_ids"]), 2)

            collection_yaml = (tmp_root / "staging" / "collectionlevel.yaml").read_text()
            self.assertIn("collection_name: cell_line_Provenance", collection_yaml)
            self.assertIn("data_category: maintenance", collection_yaml)
            self.assertIn("owner_principal: all_NIST", collection_yaml)

            dataset_yaml = (
                tmp_root / "staging" / "bulk" / "CellExpansion-000_v1.yaml"
            ).read_text()
            self.assertIn("original_upload_location:", dataset_yaml)
            self.assertIn("starting_material_type: cells", dataset_yaml)
            self.assertNotIn("workflow_id:", dataset_yaml)
            self.assertNotIn("workflow_type:", dataset_yaml)
            self.assertNotIn("workflow_notes:", dataset_yaml)

            archive_file = (
                tmp_root
                / "archive"
                / "cell_expansion_collection"
                / "CellExpansion-000_v1"
                / full_bundle_name
            )
            self.assertTrue(archive_file.exists())


if __name__ == "__main__":
    unittest.main()
