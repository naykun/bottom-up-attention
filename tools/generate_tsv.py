#!/usr/bin/env python


"""Generate bottom-up attention features as a tsv file. Can use multiple gpus, each produces a 
   separate tsv file that can be merged later (e.g. by using merge_tsv function). 
   Modify the load_image_ids script as necessary for your data location. """


# Example:

# python ./tools/generate_tsv.py --cfg experiments/cfgs/faster_rcnn_end2end_resnet.yml --def models/vg/ResNet-101/faster_rcnn_end2end_final/test.prototxt --out feature/VG/VG_resnet101_faster_rcnn_genome.tsv --net data/faster_rcnn_models/resnet101_faster_rcnn_final.caffemodel --total_group 1 --group_id 0 --split genome


# ./tools/generate_tsv.py --gpu 0,1,2,3,4,5,6,7 --cfg experiments/cfgs/faster_rcnn_end2end_resnet.yml --def models/vg/ResNet-101/faster_rcnn_end2end_final/test.prototxt --out test2014_resnet101_faster_rcnn_genome.tsv --net data/faster_rcnn_models/resnet101_faster_rcnn_final.caffemodel --split coco_test2014

# ./tools/generate_tsv.py --gpu 0 --cfg experiments/cfgs/faster_rcnn_end2end_resnet.yml --def models/vg/ResNet-101/faster_rcnn_end2end_final/test.prototxt --out /coc/scratch/panderson43/tsv/nocaps/nocaps_val_resnet101_faster_rcnn_genome.tsv --net data/faster_rcnn_models/resnet101_faster_rcnn_final.caffemodel --split nocaps_val

# ./tools/generate_tsv.py --gpu 0 --cfg experiments/cfgs/faster_rcnn_end2end_resnet.yml --def models/vg/ResNet-101/faster_rcnn_end2end_final/test.prototxt --out /coc/scratch/panderson43/tsv/nocaps_36/nocaps_val_resnet101_faster_rcnn_genome.tsv --net data/faster_rcnn_models/resnet101_faster_rcnn_final.caffemodel --split nocaps_val

#./tools/generate_tsv.py --gpu 0,1 --cfg experiments/cfgs/faster_rcnn_end2end_resnet.yml --def models/vg/ResNet-101/faster_rcnn_end2end_final/test.prototxt --out /coc/scratch/panderson43/tsv/nocaps_36/nocaps_test_resnet101_faster_rcnn_genome_36.tsv --net data/faster_rcnn_models/resnet101_faster_rcnn_final.caffemodel --split nocaps_test

#./tools/generate_tsv.py --gpu 0 --cfg experiments/cfgs/faster_rcnn_end2end_resnet.yml --def models/vg/ResNet-101/faster_rcnn_end2end_final/test.prototxt --out /coc/scratch/panderson43/tsv/test2014/test2014_resnet101_faster_rcnn_genome.tsv.3 --net data/faster_rcnn_models/resnet101_faster_rcnn_final.caffemodel --split coco_test2014

#./tools/generate_tsv.py --gpu 0 --cfg experiments/cfgs/faster_rcnn_end2end_resnet.yml --def models/vg/ResNet-101/faster_rcnn_end2end_final/test.prototxt --out /coc/scratch/panderson43/tsv/nocaps/nocaps_test_resnet101_faster_rcnn_genome.tsv.4 --net data/faster_rcnn_models/resnet101_faster_rcnn_final.caffemodel --split nocaps_test

#./tools/generate_tsv.py --gpu 0,1,2,3 --cfg experiments/cfgs/faster_rcnn_end2end_resnet.yml --def models/vg/ResNet-101/faster_rcnn_end2end_final/test.prototxt --out /coc/scratch/panderson43/tsv/openimages/openimages_trainsubset_resnet101_faster_rcnn_genome.tsv --net data/faster_rcnn_models/resnet101_faster_rcnn_final.caffemodel --split openimages_missing
BUTD_ROOT = '/opt/butd/'
import os, sys
sys.path.insert(0, BUTD_ROOT + "/tools")
os.environ['GLOG_minloglevel'] = '2'

import _init_paths
from fast_rcnn.config import cfg, cfg_from_file
from fast_rcnn.test import im_detect,_get_blobs
from fast_rcnn.nms_wrapper import nms
from utils.timer import Timer
import json_lines
import jsonlines

import caffe
import argparse
import pprint
import time, os, sys
import base64
import numpy as np
import cv2
import csv
from multiprocessing import Process
import random
import json
import pdb
import pandas as pd
import zlib

csv.field_size_limit(sys.maxsize)


FIELDNAMES = ['image_id', 'image_w','image_h','num_boxes', 'boxes', 'features', 'cls_prob']

# Settings for the number of features per image. To re-create pretrained features with 36 features
# per image, set both values to 36. 
MIN_BOXES = 36
MAX_BOXES = 36

def open_tsv(fname, folder):
    print("Opening %s Data File..." % fname)
    df = pd.read_csv(fname, sep='\t', names=["caption","url"], usecols=range(0,2))
    df['folder'] = folder
    print("Processing", len(df), " Images:")
    return df
def _file_name(row):
    return "%s/%s" % (row['folder'], (zlib.crc32(row['url'].encode('utf-8')) & 0xffffffff))

def load_image_ids(split_name, group_id, total_group, image_ids=None):
    ''' Load a list of (path,image_id tuples). Modify this to suit your data locations. '''
    split = []
    if split_name == 'coco_train2014':
      with open('/srv/share/datasets/coco/annotations/captions_train2014.json') as f:
        data = json.load(f)
        for item in data['images']:
          image_id = int(item['id'])
          filepath = os.path.join('/srv/share/datasets/coco/images/train2014', item['file_name'])
          split.append((filepath,image_id))
      
      total_num = len(split)
      per_num = int(np.ceil(total_num / total_group))+1
    
      if group_id == total_num-1:
        split = split[int(group_id * per_num):]
      else:
        split = split[int(group_id * per_num):int((group_id+1)*per_num)]

    elif split_name == 'coco_val2014':
      with open('/srv/share/datasets/coco/annotations/captions_val2014.json') as f:
        data = json.load(f)
        for item in data['images']:
          image_id = int(item['id'])
          filepath = os.path.join('/srv/share/datasets/coco/images/val2014', item['file_name'])
          split.append((filepath,image_id))
      total_num = len(split)
      per_num = int(np.ceil(total_num / total_group))+1
    
      if group_id == total_num-1:
        split = split[int(group_id * per_num):]
      else:
        split = split[int(group_id * per_num):int((group_id+1)*per_num)]
    
    elif split_name == 'coco_test2015':
      with open('/srv/share/datasets/coco/annotations/image_info_test2015.json') as f:
        data = json.load(f)
        for item in data['images']:
          image_id = int(item['id'])
          filepath = os.path.join('/srv/share/datasets/coco/images/test2015/', item['file_name'])
          split.append((filepath,image_id))

      total_num = len(split)
      per_num = int(np.ceil(total_num / total_group))+1
    
      if group_id == total_num-1:
        split = split[int(group_id * per_num):]
      else:
        split = split[int(group_id * per_num):int((group_id+1)*per_num)]
    elif split_name == 'genome':
      with open('data/vg/image_data.json') as f:
        for item in json.load(f):
          image_id = int(item['image_id'])
          filepath = os.path.join('data/vg/', item['url'].split('rak248/')[-1])
          split.append((filepath,image_id))

      total_num = len(split)
      per_num = int(np.ceil(total_num / total_group))
      if group_id == total_num-1:
        split = split[int(group_id * per_num):]
      else:
        split = split[int(group_id * per_num):int((group_id+1)*per_num)]
    elif split_name == 'flickr30k':
      with open('data/flickr30k/annotations/instances_flickr_train.json') as f:
        for item in json.load(f)['images']:
          image_id = int(item['id'])
          filepath = os.path.join('data/flickr30k/flickr30k_images', item['file_name'])
          split.append((filepath,image_id))      
      with open('data/flickr30k/annotations/instances_flickr_val.json') as f:
        for item in json.load(f)['images']:
          image_id = int(item['id'])
          filepath = os.path.join('data/flickr30k/flickr30k_images', item['file_name'])
          split.append((filepath,image_id)) 
      with open('data/flickr30k/annotations/instances_flickr_val2.json') as f:
        for item in json.load(f)['images']:
          image_id = int(item['id'])
          filepath = os.path.join('data/flickr30k/flickr30k_images', item['file_name'])
          split.append((filepath,image_id)) 
      with open('data/flickr30k/annotations/instances_flickr_test.json') as f:
        for item in json.load(f)['images']:
          image_id = int(item['id'])
          filepath = os.path.join('data/flickr30k/flickr30k_images', item['file_name'])
          split.append((filepath,image_id))           

      total_num = len(split)
      per_num = int(np.ceil(total_num / total_group))+1
    
      if group_id == total_num-1:
        split = split[int(group_id * per_num):]
      else:
        split = split[int(group_id * per_num):int((group_id+1)*per_num)]

    elif split_name == 'flickr30k_test':

      file_path_entry = []
      split = []
      with jsonlines.open('data/flickr30k/all_data_final_test_set0_2014.jsonline') as reader:
        for annotation in reader:
          filepath = annotation['img_path']
          if filepath not in file_path_entry:
            file_path_entry.append(filepath)

      for filepath in file_path_entry:
        image_id = int(filepath.split('.')[0])
        filepath = os.path.join('data/flickr30k/flickr30k_images', filepath)
        split.append((filepath,image_id))           

    elif split_name == "nocaps_val":
      with open('data/nocaps/image_info_nocap_val.v0.1.json') as f:
        data = json.load(f)
        for item in data['images']:
          image_id = int(item['id'])
          filepath = os.path.join('/srv/share/datasets/nocaps/images/val/', item['file_name'])
          split.append((filepath,image_id))
    elif split_name == "nocaps_test":
      with open('data/nocaps/image_info_nocap_test.v0.1.json') as f:
        data = json.load(f)
        for item in data['images']:
          image_id = int(item['id'])+4500
          filepath = os.path.join('/srv/share/datasets/nocaps/images/test/', item['file_name'])
          split.append((filepath,image_id))
    elif split_name == "openimages_missing":
      with open('openimages_missing_train_ids.txt') as f:
        for line in f.readlines():
          image_id = line.split()[0]
          filepath = os.path.join('/srv/share/datasets/vg_oid_coco_combined/trainv4/', line.split()[1])
          split.append((filepath,image_id))
    elif split_name == "conceptual_image_train":
      df = open_tsv('/srv/share/datasets/conceptual_caption/DownloadConceptualCaptions/Train_GCC-training.tsv', 'training')
      total_num = len(df)
      per_num = int(np.ceil(total_num / total_group))
      current_df = df[int(group_id * per_num):int((group_id+1)*per_num)]
      for i, img in enumerate(current_df.iterrows()):
        caption = img[1]['caption'].decode("utf8")
        url = img[1]['url']
        im_name = _file_name(img[1])
        image_id = np.uint64(im_name.split('/')[1])
        filepath = os.path.join('/srv/share/datasets/conceptual_caption/DownloadConceptualCaptions', im_name)
        split.append((filepath, image_id))
    elif split_name == "conceptual_image_val":
      df = open_tsv('/srv/share/datasets/conceptual_caption/DownloadConceptualCaptions/Validation_GCC-1.1.0-Validation.tsv', 'validation')
      total_num = len(df)
      per_num = int(np.ceil(total_num / total_group))
      current_df = df[int(group_id * per_num):int((group_id+1)*per_num)]
      for i, img in enumerate(current_df.iterrows()):
        caption = img[1]['caption'].decode("utf8")
        url = img[1]['url']
        im_name = _file_name(img[1])
        image_id = np.uint64(im_name.split('/')[1])
        filepath = os.path.join('/srv/share/datasets/conceptual_caption/DownloadConceptualCaptions', im_name)
        split.append((filepath, image_id))
    elif split_name == "VCR":
      # with open('VCR/train.jsonl') as f:
      image_path = {}
      with open('data/VCR/train.jsonl', 'rb') as f: # opening file in binary(rb) mode    
        for item in json_lines.reader(f):
          if item['img_fn'] not in image_path:
            image_path[item['img_fn']] = 1

      with open('data/VCR/val.jsonl', 'rb') as f: # opening file in binary(rb) mode    
        for item in json_lines.reader(f):
          if item['img_fn'] not in image_path:
            image_path[item['img_fn']] = 1
      with open('data/VCR/test.jsonl', 'rb') as f: # opening file in binary(rb) mode    
        for item in json_lines.reader(f):
          if item['img_fn'] not in image_path:
            image_path[item['img_fn']] = 1

      for image_p in image_path.keys():
        filepath = os.path.join('data/VCR/vcr1images',image_p)
        split.append((filepath, image_p))

      total_num = len(split)
      per_num = int(np.ceil(total_num / total_group))
      
      if group_id == total_num-1:
        split = split[int(group_id * per_num):]
      else:
        split = split[int(group_id * per_num):int((group_id+1)*per_num)]

    elif split_name == "refcoco_unc":
      with open('data/detections/refcoco_unc/res101_coco_minus_refer_notime_dets.json') as f:
        data = json.load(f)

        image_data = {}
        for det in data:
          if det['image_id'] not in image_data:
            image_data[det['image_id']] = []
          image_data[det['image_id']].append(det)

        max_num_box = max([len(box) for box in image_data.values()])
        bbox = np.zeros([len(image_data), max_num_box, 5])
        num_bbox = np.zeros(len(image_data))

        split = []
        count = 0
        for image_id, images in image_data.items():
          num = 0
          for i, image in enumerate(images):
            bbox[count, i, 1] = image['box'][0]
            bbox[count, i, 2] = image['box'][1]
            bbox[count, i, 3] = image['box'][0] + image['box'][2]
            bbox[count, i, 4] = image['box'][1] + image['box'][3]
            num += 1
          num_bbox[count] = num
          count += 1
          image_id = int(image_id)
          
          file_name = 'COCO_train2014_%012d.jpg' %image_id 
          filepath = os.path.join('/srv/share/datasets/coco/images/train2014', file_name)
          split.append((filepath,image_id))

      total_num = len(split)
      per_num = int(np.ceil(total_num / total_group))
      if group_id == total_num-1:
        split = split[int(group_id * per_num):]
      else:
        split = split[int(group_id * per_num):int((group_id+1)*per_num)]

    elif split_name == 'CUB':
      split = []
      with open('/srv/share2/mcogswell6/learn_to_ask_data/cub_meta.json') as f:
        data = json.load(f)
        for img in data['images']:
          split.append((img['img_path'], img['img_id']))

    elif split_name == 'AWA':
      split = []
      with open('/srv/share2/mcogswell6/learn_to_ask_data/awa_meta.json') as f:
        data = json.load(f)
        for img in data['images']:
          split.append((img['img_path'], img['img_id']))
    else:
      print('Unknown split')

    if image_ids is not None:
      filtered_split = []
      for item in split:
        if item[1] in image_ids:
          filtered_split.append(item)
      return filtered_split
    else:
      return split

def get_detections_from_im(net, im, image_id, conf_thresh=0.2):

    scores, boxes, attr_scores, rel_scores = im_detect(net, im)

    # Keep the original boxes, don't worry about the regresssion bbox outputs
    rois = net.blobs['rois'].data.copy()
    # unscale back to raw image space
    blobs, im_scales = _get_blobs(im, None)

    cls_boxes = rois[:, 1:5] / im_scales[0]
    cls_prob = net.blobs['cls_prob'].data
    pool5 = net.blobs['pool5_flat'].data

    # Keep only the best detections
    max_conf = np.zeros((rois.shape[0]))
    for cls_ind in range(1,cls_prob.shape[1]):
        cls_scores = scores[:, cls_ind]
        dets = np.hstack((cls_boxes, cls_scores[:, np.newaxis])).astype(np.float32)
        keep = np.array(nms(dets, cfg.TEST.NMS))
        max_conf[keep] = np.where(cls_scores[keep] > max_conf[keep], cls_scores[keep], max_conf[keep])

    keep_boxes = np.where(max_conf >= conf_thresh)[0]
    if len(keep_boxes) < MIN_BOXES:
        keep_boxes = np.argsort(max_conf)[::-1][:MIN_BOXES]
    elif len(keep_boxes) > MAX_BOXES:
        keep_boxes = np.argsort(max_conf)[::-1][:MAX_BOXES]
    
    return {
        'image_id': image_id,
        'image_h': np.size(im, 0),
        'image_w': np.size(im, 1),
        'num_boxes' : len(keep_boxes),
        'boxes': base64.b64encode(cls_boxes[keep_boxes]),
        'features': base64.b64encode(pool5[keep_boxes]), 
        'cls_prob': base64.b64encode(cls_prob[keep_boxes])
    }


def parse_args():
    """
    Parse input arguments
    """
    parser = argparse.ArgumentParser(description='Generate bbox output from a Fast R-CNN network')
    parser.add_argument('--gpu', dest='gpu_id', help='GPU id(s) to use',
                        default='0', type=str)
    parser.add_argument('--def', dest='prototxt',
                        help='prototxt file defining the network',
                        default=None, type=str)
    parser.add_argument('--net', dest='caffemodel',
                        help='model to use',
                        default=None, type=str)
    parser.add_argument('--out', dest='outfile',
                        help='output filepath',
                        default=None, type=str)
    parser.add_argument('--cfg', dest='cfg_file',
                        help='optional config file', default=None, type=str)
    parser.add_argument('--split', dest='data_split',
                        help='dataset to use',
                        default='karpathy_train', type=str)
    parser.add_argument('--set', dest='set_cfgs',
                        help='set config keys', default=None,
                        nargs=argparse.REMAINDER)
    parser.add_argument(
        '--total_group',
        help="the number of group for exracting",
        type=int,
        default=1
    )
    parser.add_argument(
        '--group_id',
        help=" group id for current analysis, used to shard",
        type=int,
        default=0
    )
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()
    return args

def generate_tsv(gpu_id, prototxt, weights, image_ids, outfile):
    # First check if file exists, and if it is complete
    wanted_ids = set([image_id[1] for image_id in image_ids])
    found_ids = set()
    if os.path.exists(outfile):
        with open(outfile) as tsvfile:
            reader = csv.DictReader(tsvfile, delimiter='\t', fieldnames = FIELDNAMES)
            for item in reader:
                found_ids.add(int(item['image_id']))
    
    missing = wanted_ids - found_ids
    if len(missing) == 0:
        print 'GPU {:d}: already completed {:d}'.format(gpu_id, len(image_ids))
    else:
        print 'GPU {:d}: missing {:d}/{:d}'.format(gpu_id, len(missing), len(image_ids))
        print missing
    
    if len(missing) > 0:
        caffe.set_mode_gpu()
        caffe.set_device(gpu_id)
        net = caffe.Net(prototxt, caffe.TEST, weights=weights)
        with open(outfile, 'ab') as tsvfile:
            writer = csv.DictWriter(tsvfile, delimiter = '\t', fieldnames = FIELDNAMES)   
            _t = {'misc' : Timer()}
            count = 0
            for im_file,image_id in image_ids:
                if image_id in missing:
                    im = cv2.imread(im_file)
                    # if im is not None and min(im.shape[:2])>=200 and im.shape[2]==3:
                    _t['misc'].tic()
                    writer.writerow(get_detections_from_im(net, im, image_id))
                    _t['misc'].toc()
                    if (count % 100) == 0:
                        print 'GPU {:d}: {:d}/{:d} {:.3f}s (projected finish: {:.2f} hours)' \
                              .format(gpu_id, count+1, len(missing), _t['misc'].average_time, 
                              _t['misc'].average_time*(len(missing)-count)/3600)
                    count += 1
                    # else:
                        # print 'image missing {:d}'.format(image_id)

if __name__ == '__main__':

    # merge_tsvs()
    # print fail
    args = parse_args()

    print('Called with args:')
    print(args)

    if args.cfg_file is not None:
        cfg_from_file(args.cfg_file)
    if args.set_cfgs is not None:
        cfg_from_list(args.set_cfgs)

    gpu_id = args.gpu_id
    gpu_list = gpu_id.split(',')
    gpus = [int(i) for i in gpu_list]

    print('Using config:')
    pprint.pprint(cfg)
    assert cfg.TEST.HAS_RPN

    image_ids = load_image_ids(args.data_split, args.group_id, args.total_group)

    outfile = '%s.%d' % (args.outfile, args.group_id)
    generate_tsv(0, args.prototxt, args.caffemodel, image_ids, outfile)
