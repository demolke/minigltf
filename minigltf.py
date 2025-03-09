import bpy
from io import BytesIO
import json
import mathutils
import numpy as np
import struct
import time

start = time.time()

jsn = BytesIO()
jsn.write(b'{')
jsn.write(b'"asset":{"version":"2.0","generator":"minigltf"},\n')

bchunk = BytesIO()

objs = [o for o in bpy.data.objects if o.type in ['MESH', 'ARMATURE']]
for a in bpy.data.armatures:
    objs += [b for b in a.bones]

accessors = []
bufferViews = []
meshes = []
materials = []
images = []
for o in objs:
    if not isinstance(o, bpy.types.Object):
        continue
    if o.type != 'MESH':
        continue

    for m in o.data.materials:
        if m not in materials:
            materials.append(m)
    

# Nodes section
jsn.write(b'"nodes":[')
for i in range(len(objs)):
    o = objs[i]
    jsn.write(b'{"name":"')
    jsn.write(o.name.encode())
    jsn.write(b'"')

    if isinstance(o, bpy.types.Bone):
        translation = o.matrix_local.to_translation()
        quaternion = o.matrix_local.to_quaternion()
        scale = o.matrix_local.to_scale()
    else:
        translation = o.location
        quaternion = o.rotation_quaternion
        if o.rotation_mode != 'QUATERNION':
            quaternion = o.rotation_euler.to_quaternion()
        scale = o.scale

    jsn.write(b',"translation": [')
    jsn.write(str(translation.x).encode())
    jsn.write(b',')
    jsn.write(str(translation.z).encode())
    jsn.write(b',')
    jsn.write(str(-translation.y).encode())
    jsn.write(b']')

    jsn.write(b',"rotation": [')
    jsn.write(str(quaternion.x).encode())
    jsn.write(b',')
    jsn.write(str(quaternion.z).encode())
    jsn.write(b',')
    jsn.write(str(-quaternion.y).encode())
    jsn.write(b',')
    jsn.write(str(quaternion.w).encode())
    jsn.write(b']')

    jsn.write(b',"scale": [')
    jsn.write(str(scale.x).encode())
    jsn.write(b',')
    jsn.write(str(scale.z).encode())
    jsn.write(b',')
    jsn.write(str(scale.y).encode())
    jsn.write(b']')

    if isinstance(o, bpy.types.Object) and o.type == 'MESH':
        meshes.append(o.data)
        jsn.write(b',"mesh": ')
        jsn.write(str(meshes.index(o.data)).encode())

    # Bones are nodes in GLTF
    children = [x for x in o.children]
    if isinstance(o, bpy.types.Object) and o.type == 'ARMATURE':
        children += [b for b in o.data.bones if b.parent is None]

    # Child nodes
    if children:
        jsn.write(b',"children":[')
        for c in range(len(children)):
            child = children[c]
            jsn.write(str(objs.index(child)).encode())
            if c < len(children) - 1:
                jsn.write(b',')
        jsn.write(b']')

    jsn.write(b'}')
    if i < len(objs) - 1:
        jsn.write(b',')

jsn.write(b'],')

# Meshes section
if meshes:
    jsn.write(b'"meshes":[')
    for i in range(len(meshes)):
        m = meshes[i]
        jsn.write(b'{"name":"')
        jsn.write(m.name.encode())
        jsn.write(b'","primitives":[{"attributes":{')

        # Vertex position
        jsn.write(b'"POSITION":')
        jsn.write(str(len(accessors)).encode())
        v = m.vertices[0]
        minv = mathutils.Vector([v.co.x, v.co.z, -v.co.y])
        maxv = mathutils.Vector([v.co.x, v.co.z, -v.co.y])
        offset = bchunk.tell()
        for l in m.loops:
            v = m.vertices[l.vertex_index]
            minv.x = min(minv.x, v.co.x)
            minv.y = min(minv.y, v.co.z)
            minv.z = min(minv.z, -v.co.y)
            maxv.x = max(maxv.x, v.co.x)
            maxv.y = max(maxv.y, v.co.z)
            maxv.z = max(maxv.z, -v.co.y)

            bchunk.write(np.float32(v.co.x))
            bchunk.write(np.float32(v.co.z))
            bchunk.write(np.float32(-v.co.y))

        accessors.append({'type': '"VEC3"', 'componentType': 5126, 'count': len(m.loops), 'min':minv, 'max':maxv})
        bufferViews.append({'byteOffset': offset, 'byteLength': len(m.loops) * 3 * 4, 'target': 34962})

        # Normals
        jsn.write(b',"NORMAL":')
        jsn.write(str(len(accessors)).encode())
        offset = bchunk.tell()
        for v in m.corner_normals:
            bchunk.write(np.float32(v.vector.x))
            bchunk.write(np.float32(v.vector.z))
            bchunk.write(np.float32(-v.vector.y))
        accessors.append({'type': '"VEC3"', 'componentType': 5126, 'count': len(m.corner_normals)})
        bufferViews.append({'byteOffset': offset, 'byteLength': len(m.corner_normals) * 3 * 4, 'target': 34962})

        # UV1 coordinates
        jsn.write(b',"TEXCOORD_0":')
        jsn.write(str(len(accessors)).encode())
        offset = bchunk.tell()
        for u in m.uv_layers[0].uv:
            bchunk.write(np.float32(u.vector.x))
            bchunk.write(np.float32(1-u.vector.y))
        accessors.append({'type': '"VEC2"', 'componentType': 5126, 'count': len(m.uv_layers[0].uv)})
        bufferViews.append({'byteOffset': offset, 'byteLength': len(m.uv_layers[0].uv) * 2 * 4, 'target': 34962})

        # UV2 coordinates
        if len(m.uv_layers) > 1:
            jsn.write(b',"TEXCOORD_1":')
            jsn.write(str(len(accessors)).encode())
            offset = bchunk.tell()
            for u in m.uv_layers[1].uv:
                bchunk.write(np.float32(u.vector.x))
                bchunk.write(np.float32(u.vector.y))
            accessors.append({'type': '"VEC2"', 'componentType': 5126, 'count': len(m.uv_layers[1].uv)})
            bufferViews.append({'byteOffset': offset, 'byteLength': len(m.uv_layers[1].uv) * 2 * 4, 'target': 34962})

        # Face indices
        jsn.write(b'},"indices":')
        jsn.write(str(len(accessors)).encode())
        offset = bchunk.tell()
        for l in m.loop_triangles:
            bchunk.write(np.uint32(l.loops[0]))
            bchunk.write(np.uint32(l.loops[1]))
            bchunk.write(np.uint32(l.loops[2]))
        accessors.append({'type': '"SCALAR"', 'componentType': 5125, 'count': len(m.loop_triangles) * 3})
        bufferViews.append({'byteOffset': offset, 'byteLength': len(m.loop_triangles) * 3 * 4, 'target': 34963})

        jsn.write(b',"material":')
        jsn.write(str(materials.index(m.materials[0])).encode())
        jsn.write(b'}]}')

        if i < len(meshes) - 1:
            jsn.write(b',')

    jsn.write(b'],')

# Materials
if materials:
    jsn.write(b'"materials":[')
    for i in range(len(materials)):
        m = materials[i]
        tex = 'data/texture.png'
        if not tex in images:
            images.append(tex)
        jsn.write(b'{"name":"')
        jsn.write(m.name.encode())
        jsn.write(b'","pbrMetallicRoughness":{"baseColorTexture":{"index":')
        jsn.write(str(images.index(tex)).encode())
        jsn.write(b'}}}')

        if i < len(materials) - 1:
            jsn.write(b',')

    jsn.write(b'],')


# Textures
if images:
    jsn.write(b'"textures":[')
    for i in range(len(images)):
        img = images[i]
        jsn.write(b'{"source":')
        jsn.write(str(i).encode())
        jsn.write(b'}')

        if i < len(images) - 1:
            jsn.write(b',')

    jsn.write(b'],')

# Images
if images:
    jsn.write(b'"images":[')
    for i in range(len(images)):
        img = images[i]
        jsn.write(b'{"uri":"')
        jsn.write(img.encode())
        jsn.write(b'"}')

        if i < len(images) - 1:
            jsn.write(b',')

    jsn.write(b'],')


# Accessors section
if accessors:
    jsn.write(b'"accessors":[')

    for i in range(len(accessors)):
        a = accessors[i]

        jsn.write(b'{"bufferView":')
        jsn.write(str(i).encode())

        jsn.write(b',"componentType":')
        jsn.write(str(a['componentType']).encode())

        jsn.write(b',"type":')
        jsn.write(a['type'].encode())

        jsn.write(b',"count":')
        jsn.write(str(a['count']).encode())

        if 'min' in a:
            jsn.write(b',"min":[')

            # Note x,y,z has already been swizzled
            jsn.write(str(a['min'].x).encode())
            jsn.write(b',')
            jsn.write(str(a['min'].y).encode())
            jsn.write(b',')
            jsn.write(str(a['min'].z).encode())

            jsn.write(b'],"max":[')
            jsn.write(str(a['max'].x).encode())
            jsn.write(b',')
            jsn.write(str(a['max'].y).encode())
            jsn.write(b',')
            jsn.write(str(a['max'].z).encode())
            jsn.write(b']')


        jsn.write(b'}')
        if i < len(accessors) - 1:
            jsn.write(b',')

    jsn.write(b'],')

# Bufferviews sections
if bufferViews:
    jsn.write(b'"bufferViews":[')

    for i in range(len(bufferViews)):
        b = bufferViews[i]
        jsn.write(b'{"buffer":0,"byteOffset":')
        jsn.write(str(b['byteOffset']).encode())
        jsn.write(b',"byteLength":')
        jsn.write(str(b['byteLength']).encode())
        jsn.write(b',"target":')
        jsn.write(str(b['target']).encode())
        jsn.write(b'}')
        if i < len(bufferViews) - 1:
            jsn.write(b',')
    jsn.write(b'],')

# Buffers section
jsn.write(b'"buffers":[{"byteLength":')
jsn.write(str(bchunk.tell()).encode())
jsn.write(b'}],')

# Scene section
jsn.write(b'"scene":0,\n')
jsn.write(b'"scenes":[{"name":"Scene","nodes":[')

root_objs = [o for o in objs if type(o) == bpy.types.Object and o.parent is None]
for i in range(len(root_objs)):
    o = root_objs[i]
    jsn.write(str(objs.index(o)).encode())
    if i < len(root_objs) - 1:
        jsn.write(b',')

jsn.write(b']}]\n')
jsn.write(b'}')

# json must be aligned to 4-byte
while jsn.tell() % 4 != 0:
    jsn.write(str(" ").encode())

totalLength = 28 + jsn.tell() + bchunk.tell()
output = BytesIO()
output.write(np.uint32(0x46546C67) )  # magic == gLTF
output.write(np.uint32(2))            # version == 2
output.write(np.uint32(totalLength))  # total length of the file

jsn = jsn.getbuffer()
output.write(np.uint32(len(jsn)))
output.write(np.uint32(0x4E4F534A))
output.write(jsn)

output.write(np.uint32(bchunk.tell()))
output.write(np.uint32(0x004E4942))
output.write(bchunk.getbuffer())

f = open('output.glb', 'wb')
f.write(output.getbuffer())
output.close()
f.close()

json_file = open('output.json', 'w')
json_file.write(json.dumps(json.loads(jsn.tobytes()), indent=4))
json_file.close()

# for a in bpy.data.actions:
#    output.write(f'{a.name}\n'.encode())
#
#    for f in a.fcurves:
#        output.write(f'{f.data_path}\n'.encode())
#
#        for k in f.keyframe_points:
#            output.write(struct.pack('!f', k.co[0]))
#            output.write(struct.pack('!f', k.co[1]))


print(time.time() - start)
