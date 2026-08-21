from rest_framework import serializers

from mlcore.models import ModelVersion


class ModelVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ModelVersion
        fields = [
            "id", "name", "version", "trained_at", "dataset_version", "features",
            "training_config", "metrics", "validation_metrics", "selection_criterion",
            "status", "artifact_path",
        ]
        read_only_fields = fields
