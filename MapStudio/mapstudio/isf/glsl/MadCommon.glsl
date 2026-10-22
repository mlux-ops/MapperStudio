// MapStudio implementation of the "MadCommon.glsl" include that MadMapper materials expect.
// Written from the API listed in the Materials guide; the formulas are the standard ones.
#ifndef MAPSTUDIO_MADCOMMON_GLSL
#define MAPSTUDIO_MADCOMMON_GLSL

#define PI 3.1415926535897932384626433832795
#define TWO_PI 6.283185307179586476925286766559
#define HALF_PI 1.5707963267948966192313216916398

#define saturate(x) clamp( x, 0.0, 1.0 )
#define lerp(x,y,t) mix( x, y, t )

//! Returns the luminance of a RGB color (Rec. 709 weights)
float luma( vec3 color ) {
    return dot( color, vec3( 0.2126, 0.7152, 0.0722 ) );
}

//! Returns the luminance of a RGB color
float luminance( vec3 color ) {
    return luma( color );
}

//! Luminance based rgb8/linear conversion
vec3 linearToRgb( vec3 color, vec3 range ) {
    return pow( max( color, vec3( 0.0 ) ), 1.0 / max( range, vec3( 1e-4 ) ) );
}

//! Luminance based rgb8/linear conversion
vec3 rgbToLinear( vec3 color, vec3 range ) {
    return pow( max( color, vec3( 0.0 ) ), range );
}

//! Contrast, saturation, brightness. For all settings: 1.0 = 100% 0.5 = 50% 1.5 = 150%
vec3 applyContrastSaturationBrightness( vec3 color, float contrast, float saturation, float brightness ) {
    vec3 brt = color * brightness;
    float l = luma( brt );
    vec3 sat = mix( vec3( l ), brt, saturation );
    return mix( vec3( 0.5 ), sat, contrast );
}

//! Returns HSV values for RGB input color
vec3 rgb2hsv( vec3 c ) {
    vec4 K = vec4( 0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0 );
    vec4 p = mix( vec4( c.bg, K.wz ), vec4( c.gb, K.xy ), step( c.b, c.g ) );
    vec4 q = mix( vec4( p.xyw, c.r ), vec4( c.r, p.yzx ), step( p.x, c.r ) );
    float d = q.x - min( q.w, q.y );
    float e = 1.0e-10;
    return vec3( abs( q.z + ( q.w - q.y ) / ( 6.0 * d + e ) ), d / ( q.x + e ), q.x );
}

//! Returns RGB values for HSV input color
vec3 hsv2rgb( vec3 c ) {
    vec4 K = vec4( 1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0 );
    vec3 p = abs( fract( c.xxx + K.xyz ) * 6.0 - K.www );
    return c.z * mix( K.xxx, clamp( p - K.xxx, 0.0, 1.0 ), c.y );
}

//! Convenience overload used by some shipped shaders
vec3 hsv2rgb( float h, float s, float v ) {
    return hsv2rgb( vec3( h, s, v ) );
}

//! Returns the Hue value for RGB input color
float rgb2hue( vec3 color ) {
    return rgb2hsv( color ).x;
}

//! Cheap pseudo random number in [0,1] from a 2D seed
float rand( vec2 co ) {
    return fract( sin( dot( co, vec2( 12.9898, 78.233 ) ) ) * 43758.5453123 );
}

float rand( float x ) {
    return fract( sin( x * 12.9898 ) * 43758.5453123 );
}

#endif
