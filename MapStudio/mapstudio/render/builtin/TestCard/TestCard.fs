/*{
    "CREDIT": "MapStudio",
    "DESCRIPTION": "Built-in alignment test card: grid, diagonals, centre circle and corner markers",
    "VSN": "1.0",
    "INPUTS": [
        { "NAME": "divisions_x", "LABEL": "Divisions X", "TYPE": "int", "DEFAULT": 8, "MIN": 1, "MAX": 64 },
        { "NAME": "divisions_y", "LABEL": "Divisions Y", "TYPE": "int", "DEFAULT": 8, "MIN": 1, "MAX": 64 },
        { "NAME": "front_color", "LABEL": "Color/Front Color", "TYPE": "color", "DEFAULT": [1.0, 1.0, 1.0, 1.0] },
        { "NAME": "back_color", "LABEL": "Color/Back Color", "TYPE": "color", "DEFAULT": [0.0, 0.0, 0.0, 1.0] },
        { "NAME": "show_circle", "LABEL": "Circle", "TYPE": "bool", "DEFAULT": true }
    ]
}*/

float lineMask(float coord, float divisions, float thickness)
{
    float f = fract(coord * divisions);
    float d = min(f, 1.0 - f) / divisions;
    return 1.0 - smoothstep(0.0, thickness, d);
}

vec4 materialColorForPixel(vec2 uv)
{
    vec2 px = 1.0 / RENDERSIZE;
    float t = 1.5 * max(px.x, px.y);
    float grid = max(lineMask(uv.x, float(divisions_x), t), lineMask(uv.y, float(divisions_y), t));
    // border
    float border = step(uv.x, 2.0 * px.x) + step(1.0 - 2.0 * px.x, uv.x) + step(uv.y, 2.0 * px.y) + step(1.0 - 2.0 * px.y, uv.y);
    // diagonals
    vec2 c = uv - 0.5;
    float diag = 1.0 - smoothstep(0.0, t, min(abs(c.x - c.y), abs(c.x + c.y)));
    // centre circle with the output's aspect ratio
    float aspect = RENDERSIZE.x / RENDERSIZE.y;
    vec2 ca = vec2(c.x * aspect, c.y);
    float r = length(ca);
    float circle = show_circle ? 1.0 - smoothstep(0.0, t, abs(r - 0.4)) : 0.0;
    float dot_ = 1.0 - smoothstep(0.0, t * 3.0, r - 0.01);
    float m = clamp(grid + border + diag * 0.6 + circle + dot_, 0.0, 1.0);
    // colour wash so orientation is visible: red tint top-left, green top-right, blue bottom
    vec3 tint = vec3(uv.y * (1.0 - uv.x), uv.y * uv.x, (1.0 - uv.y) * 0.8);
    vec4 back = vec4(mix(back_color.rgb, tint, 0.35), back_color.a);
    return mix(back, front_color, m);
}
