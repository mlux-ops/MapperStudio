// MapStudio implementation of the "MadNoise.glsl" include that MadMapper materials expect.
// The function names, parameters and value ranges follow the MadNoise guide shipped with
// MadMapper; the implementations are written from the standard definitions (value noise,
// simplex noise, cellular/Worley noise, fractal sums).  Derivative variants return the value
// in .x and the analytic/finite-difference derivatives in the remaining components.
#ifndef MAPSTUDIO_MADNOISE_GLSL
#define MAPSTUDIO_MADNOISE_GLSL

// ---------------------------------------------------------------- hashing
vec3 mad_mod289( vec3 x ) { return x - floor( x * ( 1.0 / 289.0 ) ) * 289.0; }
vec2 mad_mod289( vec2 x ) { return x - floor( x * ( 1.0 / 289.0 ) ) * 289.0; }
vec4 mad_mod289( vec4 x ) { return x - floor( x * ( 1.0 / 289.0 ) ) * 289.0; }
vec3 mad_permute( vec3 x ) { return mad_mod289( ( ( x * 34.0 ) + 1.0 ) * x ); }
vec4 mad_permute( vec4 x ) { return mad_mod289( ( ( x * 34.0 ) + 1.0 ) * x ); }
vec4 mad_taylorInvSqrt( vec4 r ) { return 1.79284291400159 - 0.85373472095314 * r; }

float mad_hash( float n ) { return fract( sin( n ) * 43758.5453123 ); }
float mad_hash( vec2 p ) { return fract( sin( dot( p, vec2( 127.1, 311.7 ) ) ) * 43758.5453123 ); }
float mad_hash( vec3 p ) { return fract( sin( dot( p, vec3( 127.1, 311.7, 74.7 ) ) ) * 43758.5453123 ); }
vec2 mad_hash2( vec2 p ) {
    p = vec2( dot( p, vec2( 127.1, 311.7 ) ), dot( p, vec2( 269.5, 183.3 ) ) );
    return fract( sin( p ) * 43758.5453123 );
}
vec3 mad_hash3( vec3 p ) {
    p = vec3( dot( p, vec3( 127.1, 311.7, 74.7 ) ), dot( p, vec3( 269.5, 183.3, 246.1 ) ), dot( p, vec3( 113.5, 271.9, 124.6 ) ) );
    return fract( sin( p ) * 43758.5453123 );
}
//! 1 -> 3 hash used by several shipped shaders
vec3 hash13( float p ) {
    vec3 p3 = fract( vec3( p ) * vec3( 0.1031, 0.1030, 0.0973 ) );
    p3 += dot( p3, p3.yzx + 33.33 );
    return fract( ( p3.xxy + p3.yzz ) * p3.zyx );
}


// ---------------------------------------------------------------- value noise [0,1]
//! Returns a 2D value noise in the range [0,1]
float vnoise( vec2 p ) {
    vec2 i = floor( p );
    vec2 f = fract( p );
    vec2 u = f * f * ( 3.0 - 2.0 * f );
    float a = mad_hash( i );
    float b = mad_hash( i + vec2( 1.0, 0.0 ) );
    float c = mad_hash( i + vec2( 0.0, 1.0 ) );
    float d = mad_hash( i + vec2( 1.0, 1.0 ) );
    return mix( mix( a, b, u.x ), mix( c, d, u.x ), u.y );
}

//! Returns a 3D value noise in the range [0,1]
float vnoise( vec3 p ) {
    vec3 i = floor( p );
    vec3 f = fract( p );
    vec3 u = f * f * ( 3.0 - 2.0 * f );
    float n000 = mad_hash( i );
    float n100 = mad_hash( i + vec3( 1.0, 0.0, 0.0 ) );
    float n010 = mad_hash( i + vec3( 0.0, 1.0, 0.0 ) );
    float n110 = mad_hash( i + vec3( 1.0, 1.0, 0.0 ) );
    float n001 = mad_hash( i + vec3( 0.0, 0.0, 1.0 ) );
    float n101 = mad_hash( i + vec3( 1.0, 0.0, 1.0 ) );
    float n011 = mad_hash( i + vec3( 0.0, 1.0, 1.0 ) );
    float n111 = mad_hash( i + vec3( 1.0, 1.0, 1.0 ) );
    return mix( mix( mix( n000, n100, u.x ), mix( n010, n110, u.x ), u.y ),
                mix( mix( n001, n101, u.x ), mix( n011, n111, u.x ), u.y ), u.z );
}

//! Returns a 2D value noise with derivatives in the range [0,1]
vec3 dvnoise( vec2 p ) {
    vec2 i = floor( p );
    vec2 f = fract( p );
    vec2 u = f * f * ( 3.0 - 2.0 * f );
    vec2 du = 6.0 * f * ( 1.0 - f );
    float a = mad_hash( i );
    float b = mad_hash( i + vec2( 1.0, 0.0 ) );
    float c = mad_hash( i + vec2( 0.0, 1.0 ) );
    float d = mad_hash( i + vec2( 1.0, 1.0 ) );
    float k0 = a, k1 = b - a, k2 = c - a, k3 = a - b - c + d;
    return vec3( k0 + k1 * u.x + k2 * u.y + k3 * u.x * u.y,
                 du * vec2( k1 + k3 * u.y, k2 + k3 * u.x ) );
}

//! Returns a 3D value noise with derivatives in the range [0,1]
vec4 dvnoise( vec3 p ) {
    float e = 0.01;
    float v = vnoise( p );
    return vec4( v, ( vnoise( p + vec3( e, 0.0, 0.0 ) ) - v ) / e,
                    ( vnoise( p + vec3( 0.0, e, 0.0 ) ) - v ) / e,
                    ( vnoise( p + vec3( 0.0, 0.0, e ) ) - v ) / e );
}

// ---------------------------------------------------------------- simplex noise [-1,1]
//! Returns a 2D simplex noise in the range [-1,1]
float noise( vec2 v ) {
    const vec4 C = vec4( 0.211324865405187, 0.366025403784439, -0.577350269189626, 0.024390243902439 );
    vec2 i  = floor( v + dot( v, C.yy ) );
    vec2 x0 = v - i + dot( i, C.xx );
    vec2 i1 = ( x0.x > x0.y ) ? vec2( 1.0, 0.0 ) : vec2( 0.0, 1.0 );
    vec4 x12 = x0.xyxy + C.xxzz;
    x12.xy -= i1;
    i = mad_mod289( i );
    vec3 p = mad_permute( mad_permute( i.y + vec3( 0.0, i1.y, 1.0 ) ) + i.x + vec3( 0.0, i1.x, 1.0 ) );
    vec3 m = max( 0.5 - vec3( dot( x0, x0 ), dot( x12.xy, x12.xy ), dot( x12.zw, x12.zw ) ), 0.0 );
    m = m * m;
    m = m * m;
    vec3 x = 2.0 * fract( p * C.www ) - 1.0;
    vec3 h = abs( x ) - 0.5;
    vec3 ox = floor( x + 0.5 );
    vec3 a0 = x - ox;
    m *= 1.79284291400159 - 0.85373472095314 * ( a0 * a0 + h * h );
    vec3 g;
    g.x = a0.x * x0.x + h.x * x0.y;
    g.yz = a0.yz * x12.xz + h.yz * x12.yw;
    return 130.0 * dot( m, g );
}

//! Returns a 3D simplex noise in the range [-1,1]
float noise( vec3 v ) {
    const vec2 C = vec2( 1.0 / 6.0, 1.0 / 3.0 );
    const vec4 D = vec4( 0.0, 0.5, 1.0, 2.0 );
    vec3 i  = floor( v + dot( v, C.yyy ) );
    vec3 x0 = v - i + dot( i, C.xxx );
    vec3 g = step( x0.yzx, x0.xyz );
    vec3 l = 1.0 - g;
    vec3 i1 = min( g.xyz, l.zxy );
    vec3 i2 = max( g.xyz, l.zxy );
    vec3 x1 = x0 - i1 + C.xxx;
    vec3 x2 = x0 - i2 + C.yyy;
    vec3 x3 = x0 - D.yyy;
    i = mad_mod289( i );
    vec4 p = mad_permute( mad_permute( mad_permute(
                 i.z + vec4( 0.0, i1.z, i2.z, 1.0 ) )
               + i.y + vec4( 0.0, i1.y, i2.y, 1.0 ) )
               + i.x + vec4( 0.0, i1.x, i2.x, 1.0 ) );
    float n_ = 0.142857142857;
    vec3 ns = n_ * D.wyz - D.xzx;
    vec4 j = p - 49.0 * floor( p * ns.z * ns.z );
    vec4 x_ = floor( j * ns.z );
    vec4 y_ = floor( j - 7.0 * x_ );
    vec4 x = x_ * ns.x + ns.yyyy;
    vec4 y = y_ * ns.x + ns.yyyy;
    vec4 h = 1.0 - abs( x ) - abs( y );
    vec4 b0 = vec4( x.xy, y.xy );
    vec4 b1 = vec4( x.zw, y.zw );
    vec4 s0 = floor( b0 ) * 2.0 + 1.0;
    vec4 s1 = floor( b1 ) * 2.0 + 1.0;
    vec4 sh = -step( h, vec4( 0.0 ) );
    vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
    vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
    vec3 p0 = vec3( a0.xy, h.x );
    vec3 p1 = vec3( a0.zw, h.y );
    vec3 p2 = vec3( a1.xy, h.z );
    vec3 p3 = vec3( a1.zw, h.w );
    vec4 norm = mad_taylorInvSqrt( vec4( dot( p0, p0 ), dot( p1, p1 ), dot( p2, p2 ), dot( p3, p3 ) ) );
    p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
    vec4 m = max( 0.6 - vec4( dot( x0, x0 ), dot( x1, x1 ), dot( x2, x2 ), dot( x3, x3 ) ), 0.0 );
    m = m * m;
    return 42.0 * dot( m * m, vec4( dot( p0, x0 ), dot( p1, x1 ), dot( p2, x2 ), dot( p3, x3 ) ) );
}

//! Returns a 2D simplex noise with derivatives in the range [-1,1]
vec3 dnoise( vec2 p ) {
    float e = 0.001;
    float v = noise( p );
    return vec3( v, ( noise( p + vec2( e, 0.0 ) ) - v ) / e, ( noise( p + vec2( 0.0, e ) ) - v ) / e );
}

//! Returns a 3D simplex noise with derivatives in the range [-1,1]
vec4 dnoise( vec3 p ) {
    float e = 0.001;
    float v = noise( p );
    return vec4( v, ( noise( p + vec3( e, 0.0, 0.0 ) ) - v ) / e,
                    ( noise( p + vec3( 0.0, e, 0.0 ) ) - v ) / e,
                    ( noise( p + vec3( 0.0, 0.0, e ) ) - v ) / e );
}

// ---------------------------------------------------------------- worley / cellular [0,1]
//! Returns a 2D worley/cellular noise in the range [0,1]
float worleyNoise( vec2 p ) {
    vec2 i = floor( p );
    vec2 f = fract( p );
    float d = 8.0;
    for ( int y = -1; y <= 1; y++ ) {
        for ( int x = -1; x <= 1; x++ ) {
            vec2 g = vec2( float( x ), float( y ) );
            vec2 o = mad_hash2( i + g );
            vec2 r = g + o - f;
            d = min( d, dot( r, r ) );
        }
    }
    return clamp( sqrt( d ), 0.0, 1.0 );
}

//! Returns a 3D worley/cellular noise in the range [0,1]
float worleyNoise( vec3 p ) {
    vec3 i = floor( p );
    vec3 f = fract( p );
    float d = 8.0;
    for ( int z = -1; z <= 1; z++ ) {
        for ( int y = -1; y <= 1; y++ ) {
            for ( int x = -1; x <= 1; x++ ) {
                vec3 g = vec3( float( x ), float( y ), float( z ) );
                vec3 o = mad_hash3( i + g );
                vec3 r = g + o - f;
                d = min( d, dot( r, r ) );
            }
        }
    }
    return clamp( sqrt( d ), 0.0, 1.0 );
}

//! Returns a 2D worley/cellular noise with derivatives in the range [0,1]
vec3 dWorleyNoise( vec2 p ) {
    float e = 0.001;
    float v = worleyNoise( p );
    return vec3( v, ( worleyNoise( p + vec2( e, 0.0 ) ) - v ) / e, ( worleyNoise( p + vec2( 0.0, e ) ) - v ) / e );
}

//! Returns a 3D worley/cellular noise with derivatives in the range [0,1]
vec4 dWorleyNoise( vec3 p ) {
    float e = 0.001;
    float v = worleyNoise( p );
    return vec4( v, ( worleyNoise( p + vec3( e, 0.0, 0.0 ) ) - v ) / e,
                    ( worleyNoise( p + vec3( 0.0, e, 0.0 ) ) - v ) / e,
                    ( worleyNoise( p + vec3( 0.0, 0.0, e ) ) - v ) / e );
}

// ---------------------------------------------------------------- flow noise [-1,1]
//! Returns a 2D simplex noise with rotating gradients in the range [-1,1]
float flowNoise( vec2 pos, float rot ) {
    // Rotating-gradient noise: a 2D simplex noise sampled on a slowly rotating domain and
    // blended with its rotated copy so the gradients appear to turn with `rot`.
    float c = cos( rot ), s = sin( rot );
    mat2 m = mat2( c, -s, s, c );
    float a = noise( m * pos );
    float b = noise( pos + vec2( 17.3, 9.1 ) * sin( rot * 0.5 ) );
    return mix( a, b, 0.5 + 0.5 * sin( rot ) ) ;
}

//! Returns a 2D simplex noise with rotating gradients and derivatives in the range [-1,1]
vec3 dFlowNoise( vec2 pos, float rot ) {
    float e = 0.001;
    float v = flowNoise( pos, rot );
    return vec3( v, ( flowNoise( pos + vec2( e, 0.0 ), rot ) - v ) / e, ( flowNoise( pos + vec2( 0.0, e ), rot ) - v ) / e );
}

// ---------------------------------------------------------------- billowed / ridged [0,1]
//! Returns a 2D Billowed Noise in the range [0,1]
float billowedNoise( vec2 p ) { return abs( noise( p ) ); }
//! Returns a 3D Billowed Noise in the range [0,1]
float billowedNoise( vec3 p ) { return abs( noise( p ) ); }

vec3 dBillowedNoise( vec2 p ) {
    vec3 n = dnoise( p );
    return vec3( abs( n.x ), sign( n.x ) * n.yz );
}
vec4 dBillowedNoise( vec3 p ) {
    vec4 n = dnoise( p );
    return vec4( abs( n.x ), sign( n.x ) * n.yzw );
}

//! Returns a 2D Ridged Noise in the range [0,1]
float ridgedNoise( vec2 p, float ridge ) { return ridge - abs( noise( p ) ); }
float ridgedNoise( vec2 p ) { return ridgedNoise( p, 1.0 ); }
float ridgedNoise( vec3 p, float ridge ) { return ridge - abs( noise( p ) ); }
float ridgedNoise( vec3 p ) { return ridgedNoise( p, 1.0 ); }

vec3 dRidgedNoise( vec2 p, float ridge ) {
    vec3 n = dnoise( p );
    return vec3( ridge - abs( n.x ), -sign( n.x ) * n.yz );
}
vec3 dRidgedNoise( vec2 p ) { return dRidgedNoise( p, 1.0 ); }
vec4 dRidgedNoise( vec3 p, float ridge ) {
    vec4 n = dnoise( p );
    return vec4( ridge - abs( n.x ), -sign( n.x ) * n.yzw );
}
vec4 dRidgedNoise( vec3 p ) { return dRidgedNoise( p, 1.0 ); }

// ---------------------------------------------------------------- curl [-1,1]
//! Returns a 2D Curl of a Simplex Noise in the range [-1,1]
vec2 curlNoise( vec2 v ) {
    vec3 d = dnoise( v );
    return vec2( d.z, -d.y );
}
//! Returns a 2D Curl of a Simplex Flow Noise in the range [-1,1]
vec2 curlNoise( vec2 v, float t ) {
    vec3 d = dFlowNoise( v, t );
    return vec2( d.z, -d.y );
}

// ---------------------------------------------------------------- fractal sums
//! Returns a 2D Fractal Brownian Motion sum of Simplex Noise in the range [-1,1]
float fBm( vec2 p, int octaves, float lacunarity, float gain ) {
    float sum = 0.0, amp = 1.0, norm = 0.0;
    for ( int i = 0; i < 16; i++ ) {
        if ( i >= octaves ) break;
        sum += amp * noise( p );
        norm += amp;
        p *= lacunarity;
        amp *= gain;
    }
    return sum / max( norm, 1e-6 );
}
float fBm( vec2 p ) { return fBm( p, 4, 2.0, 0.5 ); }
float fBm( vec2 p, int octaves ) { return fBm( p, octaves, 2.0, 0.5 ); }
float fBm( vec2 p, int octaves, float lacunarity ) { return fBm( p, octaves, lacunarity, 0.5 ); }

float fBm( vec3 p, int octaves, float lacunarity, float gain ) {
    float sum = 0.0, amp = 1.0, norm = 0.0;
    for ( int i = 0; i < 16; i++ ) {
        if ( i >= octaves ) break;
        sum += amp * noise( p );
        norm += amp;
        p *= lacunarity;
        amp *= gain;
    }
    return sum / max( norm, 1e-6 );
}
float fBm( vec3 p ) { return fBm( p, 4, 2.0, 0.5 ); }
float fBm( vec3 p, int octaves ) { return fBm( p, octaves, 2.0, 0.5 ); }
float fBm( vec3 p, int octaves, float lacunarity ) { return fBm( p, octaves, lacunarity, 0.5 ); }

vec3 dfBm( vec2 p, int octaves, float lacunarity, float gain ) {
    vec3 sum = vec3( 0.0 );
    float amp = 1.0, norm = 0.0, freq = 1.0;
    for ( int i = 0; i < 16; i++ ) {
        if ( i >= octaves ) break;
        vec3 n = dnoise( p * freq );
        sum += amp * vec3( n.x, n.yz * freq );
        norm += amp;
        freq *= lacunarity;
        amp *= gain;
    }
    return sum / max( norm, 1e-6 );
}
vec3 dfBm( vec2 p ) { return dfBm( p, 4, 2.0, 0.5 ); }
vec4 dfBm( vec3 p, int octaves, float lacunarity, float gain ) {
    vec4 sum = vec4( 0.0 );
    float amp = 1.0, norm = 0.0, freq = 1.0;
    for ( int i = 0; i < 16; i++ ) {
        if ( i >= octaves ) break;
        vec4 n = dnoise( p * freq );
        sum += amp * vec4( n.x, n.yzw * freq );
        norm += amp;
        freq *= lacunarity;
        amp *= gain;
    }
    return sum / max( norm, 1e-6 );
}
vec4 dfBm( vec3 p ) { return dfBm( p, 4, 2.0, 0.5 ); }

//! Returns a 2D Fractal Brownian Motion sum of Billowed Noise
float billowyTurbulence( vec2 p, int octaves, float lacunarity, float gain ) {
    float sum = 0.0, amp = 1.0, norm = 0.0;
    for ( int i = 0; i < 16; i++ ) {
        if ( i >= octaves ) break;
        sum += amp * billowedNoise( p );
        norm += amp;
        p *= lacunarity;
        amp *= gain;
    }
    return sum / max( norm, 1e-6 ) * 2.0 - 1.0;
}
float billowyTurbulence( vec2 p ) { return billowyTurbulence( p, 4, 2.0, 0.5 ); }
float billowyTurbulence( vec3 p, int octaves, float lacunarity, float gain ) {
    float sum = 0.0, amp = 1.0, norm = 0.0;
    for ( int i = 0; i < 16; i++ ) {
        if ( i >= octaves ) break;
        sum += amp * billowedNoise( p );
        norm += amp;
        p *= lacunarity;
        amp *= gain;
    }
    return sum / max( norm, 1e-6 ) * 2.0 - 1.0;
}
float billowyTurbulence( vec3 p ) { return billowyTurbulence( p, 4, 2.0, 0.5 ); }
vec3 dBillowyTurbulence( vec2 p, int octaves, float lacunarity, float gain ) {
    float e = 0.001;
    float v = billowyTurbulence( p, octaves, lacunarity, gain );
    return vec3( v, ( billowyTurbulence( p + vec2( e, 0.0 ), octaves, lacunarity, gain ) - v ) / e,
                    ( billowyTurbulence( p + vec2( 0.0, e ), octaves, lacunarity, gain ) - v ) / e );
}
vec3 dBillowyTurbulence( vec2 p ) { return dBillowyTurbulence( p, 4, 2.0, 0.5 ); }
vec4 dBillowyTurbulence( vec3 p, int octaves, float lacunarity, float gain ) {
    float e = 0.001;
    float v = billowyTurbulence( p, octaves, lacunarity, gain );
    return vec4( v, ( billowyTurbulence( p + vec3( e, 0.0, 0.0 ), octaves, lacunarity, gain ) - v ) / e,
                    ( billowyTurbulence( p + vec3( 0.0, e, 0.0 ), octaves, lacunarity, gain ) - v ) / e,
                    ( billowyTurbulence( p + vec3( 0.0, 0.0, e ), octaves, lacunarity, gain ) - v ) / e );
}
vec4 dBillowyTurbulence( vec3 p ) { return dBillowyTurbulence( p, 4, 2.0, 0.5 ); }

//! Returns a 2D Ridged Multi-Fractal sum of Simplex Noise in the range [-1,1]
float ridgedMF( vec2 p, float ridgeOffset, int octaves, float lacunarity, float gain ) {
    float sum = 0.0, amp = 0.5, prev = 1.0, norm = 0.0;
    for ( int i = 0; i < 16; i++ ) {
        if ( i >= octaves ) break;
        float n = ridgedNoise( p, ridgeOffset );
        n = n * n;
        sum += n * amp * prev;
        norm += amp;
        prev = n;
        p *= lacunarity;
        amp *= gain;
    }
    return sum / max( norm, 1e-6 ) * 2.0 - 1.0;
}
float ridgedMF( vec2 p, float ridgeOffset ) { return ridgedMF( p, ridgeOffset, 4, 2.0, 0.5 ); }
float ridgedMF( vec2 p ) { return ridgedMF( p, 1.0, 4, 2.0, 0.5 ); }
float ridgedMF( vec3 p, float ridgeOffset, int octaves, float lacunarity, float gain ) {
    float sum = 0.0, amp = 0.5, prev = 1.0, norm = 0.0;
    for ( int i = 0; i < 16; i++ ) {
        if ( i >= octaves ) break;
        float n = ridgedNoise( p, ridgeOffset );
        n = n * n;
        sum += n * amp * prev;
        norm += amp;
        prev = n;
        p *= lacunarity;
        amp *= gain;
    }
    return sum / max( norm, 1e-6 ) * 2.0 - 1.0;
}
float ridgedMF( vec3 p, float ridgeOffset ) { return ridgedMF( p, ridgeOffset, 4, 2.0, 0.5 ); }
float ridgedMF( vec3 p ) { return ridgedMF( p, 1.0, 4, 2.0, 0.5 ); }
vec3 dRidgedMF( vec2 p, float ridgeOffset, int octaves, float lacunarity, float gain ) {
    float e = 0.001;
    float v = ridgedMF( p, ridgeOffset, octaves, lacunarity, gain );
    return vec3( v, ( ridgedMF( p + vec2( e, 0.0 ), ridgeOffset, octaves, lacunarity, gain ) - v ) / e,
                    ( ridgedMF( p + vec2( 0.0, e ), ridgeOffset, octaves, lacunarity, gain ) - v ) / e );
}
vec3 dRidgedMF( vec2 p, float ridgeOffset ) { return dRidgedMF( p, ridgeOffset, 4, 2.0, 0.5 ); }
vec3 dRidgedMF( vec2 p ) { return dRidgedMF( p, 1.0, 4, 2.0, 0.5 ); }
vec4 dRidgedMF( vec3 p, float ridgeOffset, int octaves, float lacunarity, float gain ) {
    float e = 0.001;
    float v = ridgedMF( p, ridgeOffset, octaves, lacunarity, gain );
    return vec4( v, ( ridgedMF( p + vec3( e, 0.0, 0.0 ), ridgeOffset, octaves, lacunarity, gain ) - v ) / e,
                    ( ridgedMF( p + vec3( 0.0, e, 0.0 ), ridgeOffset, octaves, lacunarity, gain ) - v ) / e,
                    ( ridgedMF( p + vec3( 0.0, 0.0, e ), ridgeOffset, octaves, lacunarity, gain ) - v ) / e );
}
vec4 dRidgedMF( vec3 p, float ridgeOffset ) { return dRidgedMF( p, ridgeOffset, 4, 2.0, 0.5 ); }
vec4 dRidgedMF( vec3 p ) { return dRidgedMF( p, 1.0, 4, 2.0, 0.5 ); }

#endif
