"""
Bootloader implementation for uboot based platforms
"""

import platform
import subprocess
import os
import re
from shlex import split
import click

from ..common import (
   HOST_PATH,
   IMAGE_DIR_PREFIX,
   IMAGE_PREFIX,
   run_command,
)
from .onie import OnieInstallerBootloader

class UbootBootloader(OnieInstallerBootloader):

    NAME = 'uboot'

    def get_installed_images(self):
        images = []
        proc = subprocess.Popen(["/usr/bin/fw_printenv", "-n", "sonic_version_1"], text=True, stdout=subprocess.PIPE)
        (out, _) = proc.communicate()
        image = out.rstrip()
        if IMAGE_PREFIX in image:
            images.append(image)
        proc = subprocess.Popen(["/usr/bin/fw_printenv", "-n", "sonic_version_2"], text=True, stdout=subprocess.PIPE)
        (out, _) = proc.communicate()
        image = out.rstrip()
        if IMAGE_PREFIX in image:
            images.append(image)
        return images

    def _get_image_slot(self, image):
        """Return 1 or 2 — the slot that holds ``image`` — or None.

        Reads sonic_version_{1,2} directly and compares with ``==`` (exact
        equality). This avoids two fragile assumptions that the earlier
        ``if image in images[N]`` callers made:

          (a) ``in`` on strings is a substring check, so when two image
              names are substrings of each other the wrong slot is picked.
          (b) ``get_installed_images()`` filters out empty slots, so the
              returned list's index does not always match the slot number.
              When slot 1 is empty the sole image lives at images[0] but
              is registered in slot 2 — the list index lies.
        """
        for slot in (1, 2):
            proc = subprocess.Popen(
                ["/usr/bin/fw_printenv", "-n", "sonic_version_{}".format(slot)],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (out, _) = proc.communicate()
            if proc.returncode == 0 and out.rstrip() == image:
                return slot
        return None

    def get_next_image(self):
        images = self.get_installed_images()
        proc = subprocess.Popen(["/usr/bin/fw_printenv", "-n", "boot_next"], text=True, stdout=subprocess.PIPE)
        (out, _) = proc.communicate()
        image = out.rstrip()
        if "sonic_image_2" in image and len(images) == 2:
            next_image_index = 1
        else:
            next_image_index = 0
        return images[next_image_index]

    def set_default_image(self, image):
        slot = self._get_image_slot(image)
        if slot is not None:
            run_command(['/usr/bin/fw_setenv', 'boot_next',
                         'run sonic_image_{}'.format(slot)])
        return True

    def set_next_image(self, image):
        slot = self._get_image_slot(image)
        if slot is not None:
            run_command(['/usr/bin/fw_setenv', 'boot_once',
                         'run sonic_image_{}'.format(slot)])
        return True

    def install_image(self, image_path):
        run_command(["bash", image_path])

    def remove_image(self, image):
        click.echo('Updating next boot ...')
        slot = self._get_image_slot(image)
        if slot is not None:
            other = 2 if slot == 1 else 1
            run_command(['/usr/bin/fw_setenv', 'boot_next',
                         'run sonic_image_{}'.format(other)])
            # Clear boot_once if it points at the slot being removed —
            # otherwise the next reboot executes "run sonic_image_<removed>"
            # and lands on now-empty / stale env pointers, which can brick
            # platforms whose sonic_image_N boot script references slot-
            # specific values (e.g. BMCs with fit_name_old / linuxargs_old).
            proc = subprocess.Popen(
                ["/usr/bin/fw_printenv", "-n", "boot_once"],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (out, _) = proc.communicate()
            if proc.returncode == 0 and \
                    "sonic_image_{}".format(slot) in out:
                run_command(['/usr/bin/fw_setenv', 'boot_once', ''])
            run_command(['/usr/bin/fw_setenv',
                         'sonic_version_{}'.format(slot), 'NONE'])
        image_dir = image.replace(IMAGE_PREFIX, IMAGE_DIR_PREFIX, 1)
        click.echo('Removing image root filesystem...')
        subprocess.call(['rm','-rf', HOST_PATH + '/' + image_dir])
        click.echo('Done')

    def verify_image_platform(self, image_path):
        return os.path.isfile(image_path)

    def set_fips(self, image, enable):
        fips = "1" if enable else "0"
        proc = subprocess.Popen(["/usr/bin/fw_printenv", "linuxargs"], text=True, stdout=subprocess.PIPE)
        (out, _) = proc.communicate()
        cmdline = out.strip()
        cmdline = re.sub('^linuxargs=', '', cmdline)
        cmdline = re.sub(r' sonic_fips=[^\s]', '', cmdline) + " sonic_fips=" + fips
        run_command(['/usr/bin/fw_setenv', 'linuxargs', cmdline])
        click.echo('Done')

    def get_fips(self, image):
        proc = subprocess.Popen(["/usr/bin/fw_printenv", "linuxargs"], text=True, stdout=subprocess.PIPE)
        (out, _) = proc.communicate()
        return 'sonic_fips=1' in out

    @classmethod
    def detect(cls):
        arch = platform.machine()
        return ("arm" in arch) or ("aarch64" in arch)
