{% if not is_default_target %}
{% for schema_name in schemas %}
DEFINE SCHEMA {{ database }}.{{ schema_name }};
{% endfor %}
{% endif %}
