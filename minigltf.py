import bpy
from io import BytesIO
import json
import mathutils
import numpy as np
import struct
import time

axis_basis_change = mathutils.Matrix(((1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, -1.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)))

start = time.time()

jsn = BytesIO()
jsn.write(b'{')
jsn.write(b'"asset":{"version":"2.0","generator":"minigltf"},\n')

bchunk = BytesIO()

objs = [o for o in bpy.data.objects if o.type in ['MESH', 'ARMATURE']]
for a in bpy.data.armatures:
    objs += [b for b in a.bones]

world_matrix = {}

for a in bpy.data.objects:
    if a.type != 'ARMATURE':
        continue
    armature = a.data
    for b in armature.bones:
        world_matrix[b] = (a.matrix_world @ b.matrix_local) @ axis_basis_change

accessors = []
bufferViews = []
meshes = []
materials = []
images = []
skins = []
joints_index = {}

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
        parent = mathutils.Matrix()
        if o.parent and o.parent in world_matrix:
            parent = world_matrix[o.parent]

        result = parent.inverted_safe() @ world_matrix[o]
        (translation, quaternion, scale) = result.decompose()
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
        meshes.append(o)
        jsn.write(b',"mesh":')
        jsn.write(str(meshes.index(o)).encode())

        for m in o.modifiers:
            if m.type == 'ARMATURE' and m.object:
                if not m.object in skins:
                    skins.append(m.object)

                joints = {}
                for b in m.object.data.bones:
                    joints[b.name] = len(joints)

                joints_index[o] = joints

                jsn.write(b',"skin":')
                jsn.write(str(skins.index(m.object)).encode())

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
        m = meshes[i].data
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

        # Joints and Weights
        jsn.write(b',"JOINTS_0":')
        jsn.write(str(len(accessors)).encode())
        offset = bchunk.tell()
        accessors.append({'type': '"VEC4"', 'componentType': 5121, 'count': len(m.loops)})
        bufferViews.append({'byteOffset': offset, 'byteLength': len(m.loops) * 4, 'target': 34962})

        weights = BytesIO()

        for l in m.loops:
            v = m.vertices[l.vertex_index]

            weight = np.array([0.0, 0.0, 0.0, 0.0])
            for j in range(4):
                index = 0
                if j < len(v.groups):
                    weight[j] = v.groups[j].weight
                    if weight[j] > 0:
                        index = joints_index[meshes[i]][meshes[i].vertex_groups[v.groups[j].group].name]
                bchunk.write(np.uint8(index))

            # Normalize weights
            weight /= weight.sum()

            for j in range(4):
                weights.write(np.float32(weight[j]))

        jsn.write(b',"WEIGHTS_0":')
        jsn.write(str(len(accessors)).encode())
        offset = bchunk.tell()
        accessors.append({'type': '"VEC4"', 'componentType': 5126, 'count': len(m.loops)})
        bufferViews.append({'byteOffset': offset, 'byteLength': len(m.loops) * 4 * 4, 'target': 34962})
        bchunk.write(weights.getbuffer())

        # Face indices
        jsn.write(b'},"indices":')
        jsn.write(str(len(accessors)).encode())
        offset = bchunk.tell()
        for l in m.loop_triangles:
            bchunk.write(np.uint32(l.loops[0]))
            bchunk.write(np.uint32(l.loops[1]))
            bchunk.write(np.uint32(l.loops[2]))
        accessors.append({'type': '"SCALAR"', 'componentType': 5125, 'count': len(m.loop_triangles) * 3})
        bufferViews.append({'byteOffset': offset, 'byteLength': len(m.loop_triangles) * 4 * 4, 'target': 34963})

        # Blendshapes
        if m.shape_keys and len(m.shape_keys.key_blocks) > 1:
            jsn.write(b',"targets":[')
            for j in range(1, len(m.shape_keys.key_blocks)):
                s = m.shape_keys.key_blocks[j].data

                v = s[0].co - m.vertices[0].co
                minv = mathutils.Vector([v.x, v.z, -v.y])
                maxv = mathutils.Vector([v.x, v.z, -v.y])
                jsn.write(b'{"POSITION":')
                jsn.write(str(len(accessors)).encode())
                offset = bchunk.tell()

                for l in m.loops:
                    v = s[l.vertex_index].co - m.vertices[l.vertex_index].co
                    minv.x = min(minv.x, v.x)
                    minv.y = min(minv.y, v.z)
                    minv.z = min(minv.z, -v.y)
                    maxv.x = max(maxv.x, v.x)
                    maxv.y = max(maxv.y, v.z)
                    maxv.z = max(maxv.z, -v.y)

                    bchunk.write(np.float32(v.x))
                    bchunk.write(np.float32(v.z))
                    bchunk.write(np.float32(-v.y))

                accessors.append({'type': '"VEC3"', 'componentType': 5126, 'count': len(m.loops), 'min':minv, 'max':maxv})
                bufferViews.append({'byteOffset': offset, 'byteLength': len(m.loops) * 3 * 4, 'target': 34962})
                jsn.write(b'}')

                if j < len(m.shape_keys.key_blocks) - 1:
                    jsn.write(b',')

            jsn.write(b']')

        # Material
        jsn.write(b',"material":')
        jsn.write(str(materials.index(m.materials[0])).encode())
        jsn.write(b'}]')

        # Blendshape names
        if m.shape_keys and len(m.shape_keys.key_blocks) > 1:
            jsn.write(b',"extras":{"targetNames":[')
            for j in range(1, len(m.shape_keys.key_blocks)):
                jsn.write(b'"')
                jsn.write(m.shape_keys.key_blocks[j].name.encode())
                jsn.write(b'"')
                if j < len(m.shape_keys.key_blocks) - 1:
                    jsn.write(b',')

            jsn.write(b']}')

        jsn.write(b'}')

        if i < len(meshes) - 1:
            jsn.write(b',')

    jsn.write(b'],')

# Materials
if materials:
    jsn.write(b'"materials":[')
    for i in range(len(materials)):
        m = materials[i]

        baseColor = ''
        normal = ''
        metallicRoughness = ''

        for link in m.node_tree.links:
            if link.to_node.type == 'BSDF_PRINCIPLED' and link.to_socket.name == 'Base Color' and link.from_node.type == 'TEX_IMAGE':
                baseColor = link.from_node.image.filepath

            if link.to_node.type == 'NORMAL_MAP' and link.to_socket.name == 'Color' and link.from_node.type == 'TEX_IMAGE':
                normal = link.from_node.image.filepath

            if link.from_node.type == 'SEPARATE_COLOR' and link.to_node.type == 'BSDF_PRINCIPLED' and link.to_socket.name in ('Roughness', 'Metallic'):
                for im in m.node_tree.links:
                    if im.from_node.type == 'TEX_IMAGE' and im.to_node == link.from_node:
                        metallicRoughness = im.from_node.image.filepath

            if link.from_node.type == 'TEX_IMAGE' and link.to_node.type == 'BSDF_PRINCIPLED' and link.to_socket.name in ('Roughness', 'Metallic'):
                metallicRoughness = link.from_node.image.filepath

        if not baseColor in images:
            images.append(baseColor)

        if not normal in images:
            images.append(normal)

        if not metallicRoughness in images:
            images.append(metallicRoughness)


        jsn.write(b'{"name":"')
        jsn.write(m.name.encode())
        jsn.write(b'","doubleSided":true,"pbrMetallicRoughness":{"baseColorTexture":{"index":')
        jsn.write(str(images.index(baseColor)).encode())

        if metallicRoughness:
            jsn.write(b'},"metallicRoughnessTexture":{"index":')
            jsn.write(str(images.index(metallicRoughness)).encode())
        jsn.write(b'}}')

        if normal:
            jsn.write(b',"normalTexture":{"index":')
            jsn.write(str(images.index(normal)).encode())
            jsn.write(b'}')

        jsn.write(b'}')


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
        jsn.write(b'{"uri":"')  # GLB does not support external images, but godot fortunately doesn't care
        jsn.write(img.lstrip('/').encode())
        jsn.write(b'"}')

        if i < len(images) - 1:
            jsn.write(b',')

    jsn.write(b'],')

# Skins
if skins:
    jsn.write(b'"skins":[')
    for i in range(len(skins)):
        inverse_bind_matrixes = []
        skin = skins[i]

        jsn.write(b'{"inverseBindMatrices":')
        jsn.write(str(len(accessors)).encode())
        offset = bchunk.tell()
        accessors.append({'type': '"MAT4"', 'componentType': 5126, 'count': len(skin.data.bones)})
        bufferViews.append({'byteOffset': offset, 'byteLength': len(skin.data.bones) * 4 * 4 * 4})

        jsn.write(b',"joints":[')
        for b in range(len(skin.data.bones)):
            bone = skin.data.bones[b]
            jsn.write(str(objs.index(bone)).encode())

            matrix = (axis_basis_change @ (skin.matrix_world @ bone.matrix_local)).inverted_safe()
            for column in range(0, 4):
                for row in range(0, 4):
                    bchunk.write(np.float32(matrix[row][column]))

            if b < len(skin.data.bones) - 1:
                jsn.write(b',')

        jsn.write(b']}')

        if i < len(skins) - 1:
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
        if 'target' in b:
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

f = open('data/output.glb', 'wb')
f.write(output.getbuffer())
output.close()
f.close()

json_file = open('data/output.json', 'w')
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
