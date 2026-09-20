"""Container-level tools that have no generic verb.

Lookup and snippet are reads; combine, move tag id, link destination and
reauthorize environment are the irreversible container operations.
"""

from typing import Any, Literal

from mcp.server.mcpserver.exceptions import ToolError

from google_tag_manager_mcp import client, paths
from google_tag_manager_mcp.registry import Tier, require_confirm, tool


@tool(tier=Tier.READ, methods={None: 'accounts.containers.lookup'})
def gtm_lookup_container(
    destination_id: str | None = None, tag_id: str | None = None
) -> dict[str, Any]:
    """Finds the container behind a tag id or a destination id.

    Args:
        destination_id: A destination such as AW-123456789 or G-ABCDEF1234.
        tag_id: A container public id such as GTM-ABCDEF.

    Returns:
        The Container, including its path for further calls.
    """
    if (destination_id is None) == (tag_id is None):
        raise ToolError('Pass exactly one of destination_id or tag_id')
    kwargs = {'destinationId': destination_id} if destination_id else {'tagId': tag_id}
    return client.execute(
        client.request('accounts.containers.lookup', **kwargs), mutating=False
    )


@tool(tier=Tier.READ, methods={None: 'accounts.containers.snippet'})
def gtm_get_container_snippet(container: str) -> dict[str, Any]:
    """Returns the installation snippet of a container.

    Args:
        container: Path of the form accounts/{id}/containers/{id}.

    Returns:
        snippet (the HTML to install) and, for server containers,
        containerConfig for provisioning a tagging server manually.
    """
    location = paths.expect(container, 'containers')
    return client.execute(
        client.request('accounts.containers.snippet', path=str(location)),
        mutating=False,
    )


@tool(tier=Tier.DESTRUCTIVE, methods={None: 'accounts.containers.combine'})
def gtm_combine_containers(
    container: str,
    source_container_id: str,
    setting_source: Literal['current', 'other'] = 'current',
    allow_user_permission_feature_update: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    """Merges another container of the same account into this one. Irreversible.

    Args:
        container: Path of the target container (accounts/{id}/containers/{id}).
        source_container_id: containerId of the container merged into it.
        setting_source: Whose container settings win: current (this
            container) or other (the source container).
        allow_user_permission_feature_update: Must be true if the merge would
            switch on GTM-managed user permissions for the container.
        confirm: Must be true; ask the user first.

    Returns:
        The combined Container.
    """
    location = paths.expect(container, 'containers')
    require_confirm(
        confirm, f'Combining container {source_container_id} into {location!s}'
    )
    return client.execute(
        client.request(
            'accounts.containers.combine',
            path=str(location),
            containerId=source_container_id,
            settingSource=setting_source,
            allowUserPermissionFeatureUpdate=allow_user_permission_feature_update,
        ),
        mutating=True,
    )


@tool(tier=Tier.DESTRUCTIVE, methods={None: 'accounts.containers.move_tag_id'})
def gtm_move_tag_id(
    container: str,
    tag_id: str,
    tag_name: str | None = None,
    copy_settings: bool = False,
    copy_terms_of_service: bool = False,
    copy_users: bool = False,
    allow_user_permission_feature_update: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    """Moves a Google tag id (G-XXXX) out of this container into a new one.

    Args:
        container: Path of the container that currently holds the tag id.
        tag_id: The tag id to move, for example G-ABCDEF1234.
        tag_name: Name for the newly created tag container.
        copy_settings: Copy the tag settings to the new tag.
        copy_terms_of_service: Must be true to accept the terms of service
            copied to the new tag.
        copy_users: Copy user permissions to the new tag.
        allow_user_permission_feature_update: Must be true if the move would
            switch on GTM-managed user permissions.
        confirm: Must be true; ask the user first.

    Returns:
        The new Container that owns the tag id.
    """
    location = paths.expect(container, 'containers')
    require_confirm(confirm, f'Moving tag id {tag_id} out of {location!s}')
    kwargs: dict[str, Any] = {
        'path': str(location),
        'tagId': tag_id,
        'copySettings': copy_settings,
        'copyTermsOfService': copy_terms_of_service,
        'copyUsers': copy_users,
        'allowUserPermissionFeatureUpdate': allow_user_permission_feature_update,
    }
    if tag_name is not None:
        kwargs['tagName'] = tag_name
    return client.execute(
        client.request('accounts.containers.move_tag_id', **kwargs), mutating=True
    )


@tool(tier=Tier.DESTRUCTIVE, methods={None: 'accounts.containers.destinations.link'})
def gtm_link_destination(
    container: str,
    destination_id: str,
    allow_user_permission_feature_update: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    """Links a destination (AW-, G-, DC-) to this container, unlinking it elsewhere.

    Args:
        container: Path of the container to link the destination to.
        destination_id: The destination id, for example AW-123456789.
        allow_user_permission_feature_update: Must be true if linking would
            switch on GTM-managed user permissions.
        confirm: Must be true; ask the user first.

    Returns:
        The linked Destination.
    """
    location = paths.expect(container, 'containers')
    require_confirm(confirm, f'Linking destination {destination_id} to {location!s}')
    return client.execute(
        client.request(
            'accounts.containers.destinations.link',
            parent=str(location),
            destinationId=destination_id,
            allowUserPermissionFeatureUpdate=allow_user_permission_feature_update,
        ),
        mutating=True,
    )


@tool(
    tier=Tier.DESTRUCTIVE,
    methods={None: 'accounts.containers.environments.reauthorize'},
)
def gtm_reauthorize_environment(
    environment: str, confirm: bool = False
) -> dict[str, Any]:
    """Rotates an environment's authorization code; existing preview links stop working.

    Args:
        environment: Path of the form accounts/{id}/containers/{id}/environments/{id}.
        confirm: Must be true; ask the user first.

    Returns:
        The Environment with its new authorizationCode.
    """
    location = paths.expect(environment, 'environments')
    require_confirm(confirm, f'Reauthorizing {location!s}')
    current = client.execute(
        client.request('accounts.containers.environments.get', path=str(location)),
        mutating=False,
    )
    return client.execute(
        client.request(
            'accounts.containers.environments.reauthorize',
            path=str(location),
            body=current,
        ),
        mutating=True,
    )
