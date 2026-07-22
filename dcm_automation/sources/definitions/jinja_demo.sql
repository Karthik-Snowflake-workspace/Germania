
-- Execute RBAC Macro

{{ create_dcm_project(
    database,
    schemas,
    roles,
    project_owner_role
) }}
