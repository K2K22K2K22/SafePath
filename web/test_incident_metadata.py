import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase

from Model.utils.crime_loader import (
    PUBLIC_INCIDENT_DATA_METADATA,
    load_source_metadata,
)


class IncidentMetadataTests(SimpleTestCase):
    def test_source_metadata_marks_unknown_provenance_without_inventing_it(self):
        metadata_path = Path(settings.BASE_DIR) / "data" / "source_metadata.json"

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

        self.assertEqual(
            metadata["verification_status"],
            "unverified_demonstration_data",
        )
        self.assertFalse(metadata["verified"])
        self.assertIsNone(metadata["original_source"])
        self.assertIsNone(metadata["collection_methodology"])
        self.assertIsNone(metadata["collection_date"])
        self.assertIsNone(metadata["geographical_coverage"])
        self.assertIsNone(metadata["license"])
        self.assertIsNone(metadata["redistribution_permission"])
        self.assertTrue(
            any(
                evidence.get("commit") == "a305bb22aac396c3626737e131c13c4db6a33d51"
                for evidence in metadata["repository_evidence"]
            )
        )

    def test_public_metadata_does_not_expose_repository_evidence(self):
        self.assertNotIn("repository_evidence", PUBLIC_INCIDENT_DATA_METADATA)
        self.assertFalse(PUBLIC_INCIDENT_DATA_METADATA["verified"])

    def test_missing_or_malformed_metadata_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            metadata_path = Path(temporary_directory) / "source_metadata.json"

            with patch(
                "Model.utils.crime_loader.SOURCE_METADATA_FILE",
                metadata_path,
            ):
                missing = load_source_metadata()

                metadata_path.write_text("not-json", encoding="utf-8")
                malformed = load_source_metadata()

                metadata_path.write_text("[]", encoding="utf-8")
                wrong_shape = load_source_metadata()

                metadata_path.write_text("[" * 10000 + "]" * 10000, encoding="utf-8")
                deeply_nested = load_source_metadata()

        for metadata in (missing, malformed, wrong_shape, deeply_nested):
            self.assertFalse(metadata["verified"])
            self.assertEqual(
                metadata["verification_status"],
                "unverified_demonstration_data",
            )
            self.assertIsNone(metadata["original_source"])
            self.assertIsNone(metadata["license"])

    def test_metadata_cannot_self_declare_verified_data(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            metadata_path = Path(temporary_directory) / "source_metadata.json"
            metadata_path.write_text(
                json.dumps(
                    {
                        "dataset_file": "delhi_crime_data.csv",
                        "verification_status": "verified",
                        "verified": True,
                        "original_source": "unsupported claim",
                    }
                ),
                encoding="utf-8",
            )

            with patch(
                "Model.utils.crime_loader.SOURCE_METADATA_FILE",
                metadata_path,
            ):
                metadata = load_source_metadata()

        self.assertFalse(metadata["verified"])
        self.assertEqual(
            metadata["verification_status"],
            "unverified_demonstration_data",
        )
        self.assertIsNone(metadata["original_source"])
        self.assertIsNone(metadata["record_nature"])

    def test_metadata_cannot_claim_a_different_record_nature(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            metadata_path = Path(temporary_directory) / "source_metadata.json"
            metadata_path.write_text(
                json.dumps(
                    {
                        "dataset_file": "delhi_crime_data.csv",
                        "verification_status": "unverified_demonstration_data",
                        "verified": False,
                        "record_nature": "verified police crime records",
                        "original_source": None,
                        "collection_methodology": None,
                        "collection_date": None,
                        "geographical_coverage": None,
                        "license": None,
                        "redistribution_permission": None,
                        "repository_evidence": [],
                    }
                ),
                encoding="utf-8",
            )

            with patch(
                "Model.utils.crime_loader.SOURCE_METADATA_FILE",
                metadata_path,
            ):
                metadata = load_source_metadata()

        self.assertFalse(metadata["verified"])
        self.assertIsNone(metadata["record_nature"])
