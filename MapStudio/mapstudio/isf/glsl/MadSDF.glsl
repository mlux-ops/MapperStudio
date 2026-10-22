// MapStudio implementation of the "MadSDF.glsl" include that MadMapper materials expect.
// API from the MadSDF guide shipped with MadMapper; the distance functions are the standard
// 2D signed-distance formulas.  Anti-aliasing of fill/stroke/glow uses screen-space derivatives.
#ifndef MAPSTUDIO_MADSDF_GLSL
#define MAPSTUDIO_MADSDF_GLSL

#ifndef PI
#define PI 3.1415926535897932384626433832795
#endif

// ---------------------------------------------------------------- primitives
//! Returns the signed distance of a circle
float circle( vec2 p, float radius ) { return length( p ) - radius; }
float circle( vec2 p, vec2 center, float radius ) { return length( p - center ) - radius; }

//! Returns the signed distance of a box
float rectangle( vec2 p, vec2 size ) {
    vec2 d = abs( p ) - size;
    return length( max( d, vec2( 0.0 ) ) ) + min( max( d.x, d.y ), 0.0 );
}
float rectangle( vec2 p, float radius ) { return rectangle( p, vec2( radius ) ); }
float rectangle( vec2 p, vec2 center, vec2 size ) { return rectangle( p - center, size ); }
float rectangle( vec2 p, vec2 center, float radius ) { return rectangle( p - center, vec2( radius ) ); }

//! Returns the signed distance of a rounded box
float roundedRectangle( vec2 p, vec2 size, float cornerRadius ) {
    return rectangle( p, size - vec2( cornerRadius ) ) - cornerRadius;
}
float roundedRectangle( vec2 p, vec2 center, vec2 size, float cornerRadius ) {
    return roundedRectangle( p - center, size, cornerRadius );
}

//! Returns the signed distance of an equilateral triangle
float triangle( vec2 p, float radius ) {
    const float k = 1.7320508075688772;
    p.x = abs( p.x ) - radius;
    p.y = p.y + radius / k;
    if ( p.x + k * p.y > 0.0 ) p = vec2( p.x - k * p.y, -k * p.x - p.y ) / 2.0;
    p.x -= clamp( p.x, -2.0 * radius, 0.0 );
    return -length( p ) * sign( p.y );
}
float triangle( vec2 p, vec2 center, float radius ) { return triangle( p - center, radius ); }

//! Returns the signed distance of an hexagon
float hexagon( vec2 p, float radius ) {
    const vec3 k = vec3( -0.866025404, 0.5, 0.577350269 );
    p = abs( p );
    p -= 2.0 * min( dot( k.xy, p ), 0.0 ) * k.xy;
    p -= vec2( clamp( p.x, -k.z * radius, k.z * radius ), radius );
    return length( p ) * sign( p.y );
}
float hexagon( vec2 p, vec2 center, float radius ) { return hexagon( p - center, radius ); }

//! Returns the signed distance of a line segment of the given width
float line( vec2 p, vec2 start, vec2 end, float width ) {
    vec2 pa = p - start, ba = end - start;
    float h = clamp( dot( pa, ba ) / max( dot( ba, ba ), 1e-9 ), 0.0, 1.0 );
    return length( pa - ba * h ) - width;
}
//! Variant with explicit start/end components used by some shipped shaders
float line( vec2 p, float x0, float y0, float x1, float y1, float width ) {
    return line( p, vec2( x0, y0 ), vec2( x1, y1 ), width );
}

//! Returns the signed distance of an arc centred at the origin, spanning +-angle around +y
float arc( vec2 p, float radius, float angle, float width ) {
    vec2 sc = vec2( sin( angle ), cos( angle ) );
    p.x = abs( p.x );
    float d = ( sc.y * p.x > sc.x * p.y ) ? length( p - sc * radius ) : abs( length( p ) - radius );
    return d - width;
}

// ---------------------------------------------------------------- colouring
float mad_sdfCoverage( float dist ) {
    float w = fwidth( dist ) * 0.5;
    return 1.0 - smoothstep( -w, w, dist );
}

//! Returns the colored inner distance field
vec3 fill( vec3 a, vec3 b, float dist ) { return mix( a, b, mad_sdfCoverage( dist ) ); }
vec4 fill( vec4 a, vec4 b, float dist ) { return mix( a, b, mad_sdfCoverage( dist ) ); }

//! Returns the colored border of the distance field
vec3 stroke( vec3 a, vec3 b, float dist, float width ) { return mix( a, b, mad_sdfCoverage( abs( dist ) - width ) ); }
vec4 stroke( vec4 a, vec4 b, float dist, float width ) { return mix( a, b, mad_sdfCoverage( abs( dist ) - width ) ); }
//! Variant with separate inner/outer widths
vec3 stroke( vec3 a, vec3 b, float dist, float innerWidth, float outerWidth ) {
    return mix( a, b, mad_sdfCoverage( max( dist - outerWidth, -dist - innerWidth ) ) );
}

//! Returns the colored blurred border of the distance field (additive)
vec3 glow( vec3 color, float dist, float width ) {
    return color * ( 1.0 - smoothstep( 0.0, max( width, 1e-6 ), abs( dist ) ) );
}
vec4 glow( vec4 color, float dist, float width ) {
    return color * ( 1.0 - smoothstep( 0.0, max( width, 1e-6 ), abs( dist ) ) );
}

// ---------------------------------------------------------------- operators
//! Returns the union of two signed distance field
float blend( float d1, float d2 ) { return min( d1, d2 ); }
//! Returns the smooth blend of two signed distance field
float smoothBlend( float d1, float d2, float k ) {
    float h = clamp( 0.5 + 0.5 * ( d2 - d1 ) / max( k, 1e-6 ), 0.0, 1.0 );
    return mix( d2, d1, h ) - k * h * ( 1.0 - h );
}
//! Returns the subtraction of a signed distance field by another signed distance field
float subtract( float d1, float d2 ) { return max( d1, -d2 ); }
//! Returns the intersection of two signed distance field
float intersect( float d1, float d2 ) { return max( d1, d2 ); }

// ---------------------------------------------------------------- domain transforms
//! Returns a translated position
vec2 translate( vec2 p, vec2 t ) { return p - t; }
//! Returns a rotated position
vec2 rotate( vec2 p, float a ) {
    float c = cos( a ), s = sin( a );
    return vec2( c * p.x - s * p.y, s * p.x + c * p.y );
}
//! Returns a transformed position
vec2 transform( vec2 p, mat2 m ) { return m * p; }

//! Returns the repeated position every offset
vec2 repeat( vec2 p, vec2 offset ) {
    return mod( p + 0.5 * offset, offset ) - 0.5 * offset;
}
//! Returns the repeated position every offset with the ID for the current cell
vec2 repeat( vec2 p, vec2 offset, out vec2 cellId ) {
    cellId = floor( ( p + 0.5 * offset ) / offset );
    return mod( p + 0.5 * offset, offset ) - 0.5 * offset;
}
vec2 repeat( vec2 p, vec2 offset, vec2 a, vec2 b, out vec2 cellId ) {
    vec2 id = floor( ( p + 0.5 * offset ) / offset );
    vec2 shift = a * vec2( mod( id.y, max( b.x, 1.0 ) ), mod( id.x, max( b.y, 1.0 ) ) );
    vec2 q = p - shift;
    cellId = floor( ( q + 0.5 * offset ) / offset );
    return mod( q + 0.5 * offset, offset ) - 0.5 * offset;
}
//! Returns the repeated position with an offset `a` applied every `b` rows/columns (brick layouts)
vec2 repeat( vec2 p, vec2 offset, vec2 a, vec2 b ) {
    vec2 cellId;
    return repeat( p, offset, a, b, cellId );
}
//! Returns the repeated position radially each angle
vec2 repeatRadial( vec2 p, float angle, float angleOffset, out vec2 cellId ) {
    float a = atan( p.y, p.x ) - angleOffset;
    float id = floor( ( a + 0.5 * angle ) / angle );
    cellId = vec2( id, 0.0 );
    float r = length( p );
    float na = a - id * angle;
    return vec2( cos( na ), sin( na ) ) * r;
}
vec2 repeatRadial( vec2 p, float angle, float angleOffset ) {
    vec2 cellId;
    return repeatRadial( p, angle, angleOffset, cellId );
}
vec2 repeatRadial( vec2 p, float angle, out vec2 cellId ) { return repeatRadial( p, angle, 0.0, cellId ); }
vec2 repeatRadial( vec2 p, float angle ) {
    vec2 cellId;
    return repeatRadial( p, angle, 0.0, cellId );
}

#endif
