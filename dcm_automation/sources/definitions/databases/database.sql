{% if not is_default_target %}
DEFINE DATABASE {{ database }};
{% endif %}
