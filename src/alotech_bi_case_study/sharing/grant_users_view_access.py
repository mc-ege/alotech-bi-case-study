"""Grant bi@alo-tech.com access to the authorized three-column users view."""

import os
import subprocess

from google.cloud import bigquery

PROJECT = os.environ["ALOTECH_PROJECT_ID"]
MEMBER = "user:bi@alo-tech.com"
VIEW_ID = f"{PROJECT}.alotech_shared.v_users_contact"


def main() -> None:
    """Authorize the view, grant view-level read access, and allow query jobs."""
    client = bigquery.Client(project=PROJECT, location="US")
    view = client.get_table(VIEW_ID)
    if view.table_type != "VIEW" or tuple(f.name for f in view.schema) != (
        "first_name", "last_name", "email"
    ):
        raise ValueError("Expected three-column contact view was not found")

    raw = client.get_dataset(f"{PROJECT}.alotech_raw")
    reference = view.reference.to_api_repr()
    if not any(e.entity_type == "view" and e.entity_id == reference for e in raw.access_entries):
        raw.access_entries = [*raw.access_entries, bigquery.AccessEntry(None, "view", reference)]
        client.update_dataset(raw, ["access_entries"])

    policy = client.get_iam_policy(view)
    binding = next(
        (b for b in policy.bindings if b["role"] == "roles/bigquery.dataViewer" and not b.get("condition")),
        None,
    )
    if binding is None:
        policy.bindings.append({"role": "roles/bigquery.dataViewer", "members": {MEMBER}})
        client.set_iam_policy(view, policy)
    elif MEMBER not in binding["members"]:
        binding["members"].add(MEMBER)
        client.set_iam_policy(view, policy)

    subprocess.run(
        ["gcloud", "projects", "add-iam-policy-binding", PROJECT,
         f"--member={MEMBER}", "--role=roles/bigquery.jobUser", "--quiet", "--format=none"],
        check=True,
    )
    print(f"Access configured for {MEMBER} on {VIEW_ID}")


if __name__ == "__main__":
    main()
