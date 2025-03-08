import bpy
from io import BytesIO
import json
import numpy as np
import struct
import time

chunks = []

start = time.time()

output = BytesIO()

output.write(np.uint32(0x46546C67))  # magic == gLTF
output.write(np.uint32(2))           # version == 2
output.write(np.uint32(0x726e6769))  # length == garbage, godot doesn't care

jsn = BytesIO()
jsn.write(b'{')
jsn.write(b'"asset":{"version":"2.0","generator":"minigltf"},\n')

objs = [o for o in bpy.data.objects if o.type in ['MESH', 'ARMATURE']]
for a in bpy.data.armatures:
    objs += [b for b in a.bones]
meshes = []
armatures = []

print(objs)

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
    print(o.name)
    children = [x for x in o.children]
    print(children)
    if isinstance(o, bpy.types.Object) and o.type == 'ARMATURE':
        children += [b for b in o.data.bones if b.parent is None]
    print("Children + bones" + str(children))

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
        jsn.write(b'","primitives":[')

        jsn.write(b']}')
        if i < len(meshes) - 1:
            jsn.write(b',')
    jsn.write(b'],')

# Scene section
jsn.write(b'"scene":0,\n')
jsn.write(b'"scenes":[{"name":"Scene","nodes":[')

root_objs = [o for o in objs if o.parent is None]
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

jsn = jsn.getbuffer()
output.write(np.uint32(len(jsn)))
output.write(np.uint32(0x4E4F534A))
output.write(jsn)

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

f = open('output.glb', 'wb')
f.write(output.getbuffer())
output.close()
f.close()

print(time.time() - start)
