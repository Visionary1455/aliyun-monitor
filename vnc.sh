sh << 'EOF'
P="yiwan123";D="/dev/vda";R="http://mirrors.aliyun.com/alpine/v3.23"
[ -d /sys/firmware/efi ]&&FW=uefi||FW=bios;echo $FW
apk add gdisk >/dev/null 2>&1;sgdisk -Z $D 2>/dev/null;dd if=/dev/zero of=$D bs=512 count=34 2>/dev/null;B=$(basename $D);S=$(cat /sys/block/$B/size);dd if=/dev/zero of=$D bs=512 seek=$((S-34)) count=34 2>/dev/null;sync;sleep 1;setup-interfaces -a -r;sleep 2
cat>/tmp/a<<E
KEYMAPOPTS="us us"
HOSTNAMEOPTS="-n alpine"
INTERFACESOPTS="auto lo
iface lo inet loopback
auto eth0
iface eth0 inet dhcp"
DNSOPTS="-d 223.5.5.5 8.8.8.8"
TIMEZONEOPTS="-z PRC"
PROXYOPTS="none"
APKREPOSOPTS="$R/main"
SSHDOPTS="-c openssh"
NTPOPTS="-c chrony"
USEROPTS="-a -k none"
DISKOPTS="-m sys -s 0 $D"
E
export ERASE_DISKS=$D;echo|setup-alpine -f /tmp/a -e;mkdir -p /mnt
if [ "$FW" = "uefi" ];then V=$(blkid -t TYPE=vfat -o device|grep "^$D"|head -1);X=$(blkid -t TYPE=ext4 -o device|grep "^$D"|tail -1);[ -z "$V" ]&&V=${D}1;[ -z "$X" ]&&X=${D}2;mount $X /mnt;mkdir -p /mnt/boot/efi;mount $V /mnt/boot/efi;else mount ${D}2 /mnt;mount ${D}1 /mnt/boot;fi
echo "root:$P"|chroot /mnt chpasswd;sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin yes/' /mnt/etc/ssh/sshd_config;echo -e "$R/main\n$R/community">/mnt/etc/apk/repositories;mount --bind /dev /mnt/dev;mount --bind /proc /mnt/proc;mount --bind /sys /mnt/sys;[ "$FW" = "uefi" ]&&{ modprobe efivarfs 2>/dev/null;mount --bind /sys/firmware/efi /mnt/sys/firmware/efi 2>/dev/null;}
chroot /mnt apk update;chroot /mnt apk add util-linux curl vim bash e2fsprogs;if [ "$FW" = "uefi" ];then chroot /mnt apk add grub-efi efibootmgr dosfstools;chroot /mnt grub-install --target=x86_64-efi --efi-directory=/boot/efi --removable;else chroot /mnt apk add grub grub-bios;chroot /mnt grub-install --recheck $D;fi;chroot /mnt grub-mkconfig -o /boot/grub/grub.cfg;chroot /mnt apk del syslinux 2>/dev/null;sync;[ "$FW" = "uefi" ]&&umount /mnt/boot/efi 2>/dev/null||umount /mnt/boot 2>/dev/null;umount /mnt/dev /mnt/proc /mnt/sys /mnt 2>/dev/null;reboot
EOF