import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


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
